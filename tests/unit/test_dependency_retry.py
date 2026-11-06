import unittest
from unittest.mock import Mock, patch

from pymongo.errors import OperationFailure, ServerSelectionTimeoutError
from redis.exceptions import LockError

from mrq.dependency_retry import retry_mongo_selection
from mrq.worker import Worker


class StopLoop(BaseException):
    pass


class RetryTests(unittest.TestCase):
    def test_startup_recovers_after_a_minute_with_bounded_backoff(self):
        clock = [0]
        def sleep(seconds):
            self.assertLessEqual(seconds, 10)
            clock[0] += seconds
        def operation():
            if clock[0] < 60:
                raise ServerSelectionTimeoutError("synthetic")
            return "connected"
        with patch("mrq.dependency_retry.time.monotonic", side_effect=lambda: clock[0]), patch("mrq.dependency_retry.time.sleep", side_effect=sleep):
            self.assertEqual(retry_mongo_selection(operation, Mock()), "connected")
            self.assertGreaterEqual(clock[0], 60)

    def test_startup_fails_after_two_minutes_and_does_not_log_connection_values(self):
        clock = [0]
        logger = Mock()
        def sleep(seconds):
            clock[0] += seconds
        with patch("mrq.dependency_retry.time.monotonic", side_effect=lambda: clock[0]), patch("mrq.dependency_retry.time.sleep", side_effect=sleep):
            with self.assertRaises(ServerSelectionTimeoutError):
                retry_mongo_selection(Mock(side_effect=ServerSelectionTimeoutError("sensitive-uri")), logger)
        self.assertEqual(clock[0], 120)
        self.assertNotIn("sensitive-uri", str(logger.mock_calls))

    def test_configuration_and_authorisation_failures_are_not_retried(self):
        operation = Mock(side_effect=OperationFailure("denied"))
        with self.assertRaises(OperationFailure):
            retry_mongo_selection(operation, Mock())
        operation.assert_called_once()

    def scheduler_tick(self, acquired=True, release_error=None):
        worker = Worker.__new__(Worker)
        worker.scheduler = Mock()
        worker.log = Mock()
        lock = Mock()
        lock.acquire.return_value = acquired
        lock.release.side_effect = release_error
        with patch("mrq.worker.get_current_config", return_value={"redis_prefix": "test", "scheduler_interval": 60}), patch("mrq.worker.connections"), patch("mrq.worker.LuaLock", return_value=lock) as factory, patch("mrq.worker.time.sleep", side_effect=StopLoop):
            with self.assertRaises(StopLoop):
                worker.greenlet_scheduler()
        self.assertEqual(factory.call_args.kwargs["timeout"], 180)
        return worker, lock

    def test_contended_lock_does_not_kill_worker_or_run_scheduler(self):
        worker, lock = self.scheduler_tick(acquired=False)
        worker.scheduler.check.assert_not_called()
        lock.release.assert_not_called()

    def test_expired_lease_does_not_kill_unrelated_jobs(self):
        worker, lock = self.scheduler_tick(release_error=LockError("expired"))
        worker.scheduler.check.assert_called_once()
        lock.release.assert_called_once()
        worker.log.warning.assert_called_once()

    def test_successful_tick_releases_lease(self):
        worker, lock = self.scheduler_tick()
        worker.scheduler.check.assert_called_once()
        lock.release.assert_called_once()

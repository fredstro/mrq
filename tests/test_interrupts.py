import time
import datetime
from builtins import str
from mrq.job import Job, get_job_result
from mrq.queue import Queue
from bson import ObjectId
import pytest
from mrq.context import connections
import json
import os


PROCESS_CONFIGS = [
    ["--greenlets 1"],
    ["--greenlets 2"],
    ["--greenlets 1 --processes 1"],
    ["--greenlets 2 --processes 1"]
]


@pytest.mark.parametrize(["p_flags"], PROCESS_CONFIGS)
def test_interrupt_worker_gracefully(worker, p_flags):
    """ Test what happens when we interrupt a running worker gracefully. """

    worker.start(flags=p_flags)

    job_id = worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 5}, block=False)

    time.sleep(2)

    job = Job(job_id).fetch().data
    assert job["status"] == "started"

    # Stop the worker gracefully. first job should still finish!
    os.kill(worker.process.pid, 2)

    time.sleep(1)

    # Should not be accepting new jobs!
    job_id2 = worker.send_task(
        "tests.tasks.general.Add", {"a": 42, "b": 1, "sleep": 4}, block=False, start=False)

    time.sleep(1)

    job = Job(job_id2).fetch().data
    assert job.get("status") == "queued"

    time.sleep(4)

    job = Job(job_id).fetch().data
    assert job["status"] == "success"
    assert job["result"] == 42

    job = Job(job_id2).fetch().data
    assert job.get("status") == "queued"


@pytest.mark.parametrize(["p_flags"], PROCESS_CONFIGS)
def test_interrupt_worker_double_sigint(worker, p_flags):
    """ Test what happens when we interrupt a running worker with 2 SIGINTs. """

    start_time = time.time()

    worker.start(flags=p_flags)

    job_id = worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 20}, block=False)

    while Job(job_id).fetch().data["status"] == "queued":
        time.sleep(0.1)

    job = Job(job_id).fetch().data
    assert job["status"] == "started"

    # Stop the worker gracefully. first job should still finish!
    os.kill(worker.process.pid, 2)

    time.sleep(1)

    # Should not be accepting new jobs!
    job_id2 = worker.send_task(
        "tests.tasks.general.Add", {"a": 42, "b": 1, "sleep": 20}, block=False, start=False)

    time.sleep(1)

    job2 = Job(job_id2).fetch().data
    assert job2.get("status") == "queued"

    job = Job(job_id).fetch().data
    assert job["status"] == "started"

    # Sending a second kill -2 should make it stop
    os.kill(worker.process.pid, 2)

    while Job(job_id).fetch().data["status"] == "started":
        time.sleep(0.1)

    job = Job(job_id).fetch().data
    assert job["status"] == "interrupt"

    assert time.time() - start_time < 15

    # Then try the cleaning task that requeues interrupted jobs

    assert Queue("default").size() == 1

    worker.start(queues="cleaning", deps=False, flush=False)

    res = worker.send_task(
        "mrq.basetasks.cleaning.RequeueInterruptedJobs", {}, block=True, queue="cleaning")

    assert res["requeued"] == 1

    assert Queue("default").size() == 2

    Queue("default").list_job_ids() == [str(job_id2), str(job_id)]

    job = Job(job_id).fetch().data
    assert job["status"] == "queued"
    assert job["queue"] == "default"


@pytest.mark.parametrize(["p_flags"], PROCESS_CONFIGS)
def test_interrupt_worker_sigterm(worker, p_flags):
    """ Test what happens when we interrupt a running worker with 1 SIGTERM.

        We should have had time to mark the task as 'interrupt' so that we can restart it somewhere else right away.
    """

    start_time = time.time()

    worker.start(flags=p_flags)

    job_id = worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 20}, block=False)

    time.sleep(3)

    worker.stop(block=True, sig=15, deps=False)

    time.sleep(2)

    job = Job(job_id).fetch().data
    assert job["status"] == "interrupt"

    assert time.time() - start_time < 10

    worker.stop_deps()


@pytest.mark.parametrize(["p_flags"], PROCESS_CONFIGS)
def test_interrupt_worker_sigkill(worker, p_flags):
    """ Test what happens when we interrupt a running worker with 1 SIGKILL.

        SIGKILLs can't be intercepted by the process so the job should still be in 'started' state.
    """

    start_time = time.time()

    worker.start(
        flags=p_flags + " --config tests/fixtures/config-shorttimeout.py")

    cfg = json.loads(
        worker.send_task("tests.tasks.general.GetConfig", {}, block=True))

    assert cfg["tasks"]["tests.tasks.general.Add"]["timeout"] == 200

    job_id = worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 20}, block=False)

    time.sleep(3)

    worker.stop(block=True, sig=9, deps=False)

    time.sleep(1)

    # This is a bit tricky, but when getting the job from the current python environment, its timeout should
    # be the default 3600 and not 200 because we didn't configure ourselves
    # with config-shorttimeout.py
    job = Job(job_id).fetch().data
    assert Job(job_id).fetch().timeout == 3600

    assert job["status"] == "started"

    assert time.time() - start_time < 10

    # Then try the cleaning task that requeues started jobs

    # We need to fake the datestarted
    worker.mongodb_jobs.mrq_jobs.update({"_id": ObjectId(job_id)}, {"$set": {
        "datestarted": datetime.datetime.utcnow() - datetime.timedelta(seconds=300)
    }})

    assert Queue("default").size() == 1

    worker.start(queues="cleaning", deps=False, flush=False,
                 flags=" --config tests/fixtures/config-shorttimeout.py")

    res = worker.send_task("mrq.basetasks.cleaning.RequeueStartedJobs", {
                           "timeout": 110}, block=True, queue="cleaning")

    assert res["requeued"] == 0
    assert res["started"] == 2  # current job should count too

    assert Queue("default").size() == 1

    job = Job(job_id).fetch().data
    assert job["status"] == "started"
    assert job["queue"] == "default"

    # Now do it again with a small enough timeout
    res = worker.send_task("mrq.basetasks.cleaning.RequeueStartedJobs", {
                           "timeout": 90}, block=True, queue="cleaning")

    assert res["requeued"] == 1
    assert res["started"] == 2  # current job should count too
    assert Queue("default").size() == 1

    Queue("default").list_job_ids() == [str(job_id)]

    job = Job(job_id).fetch().data
    assert job["status"] == "queued"
    assert job["queue"] == "default"


def test_worker_crash(worker):
    """ Test that when a worker crashes its running jobs are requeued """

    worker.start(queues="default")
    worker.send_task(
        "tests.tasks.general.Add",
        {"a": 41, "b": 1, "sleep": 10},
        block=False,
        queue="default"
    )

    time.sleep(5)

    worker.stop(block=True, sig=9, deps=False)

    time.sleep(1)

    # simulate worker crash
    worker.mongodb_jobs.mrq_workers.delete_many({})
    worker.start(queues="cleaning", deps=False, flush=False)

    res = worker.send_task("mrq.basetasks.cleaning.RequeueStartedJobs", {
                           "timeout": 90}, block=True, queue="cleaning")

    assert res["requeued"] == 1
    assert res["started"] == 2
    assert Queue("default").size() == 1

# def test_interrupt_redis_flush(worker):
#     """ Test what happens when we flush redis after queueing jobs.

#         The RequeueLostJobs task should put them back in redis.
#     """

#     worker.start(queues="cleaning", deps=True, flush=True)

#     job_id1 = worker.send_task("tests.tasks.general.Add", {
#                                "a": 41, "b": 1, "sleep": 10}, block=False, queue="default")
#     job_id2 = worker.send_task("tests.tasks.general.Add", {
#                                "a": 41, "b": 1, "sleep": 10}, block=False, queue="default")
#     job_id3 = worker.send_task("tests.tasks.general.Add", {
#                                "a": 41, "b": 1, "sleep": 10}, block=False, queue="otherq")

#     assert Queue("default").size() == 2
#     assert Queue("otherq").size() == 1

#     res = worker.send_task(
#         "mrq.basetasks.cleaning.RequeueLostJobs", {}, block=True, queue="cleaning")

#     # We should try the first job on each queue only, and when seeing it's there we should
#     # stop.
#     assert res["fetched"] == 2
#     assert res["requeued"] == 0

#     assert Queue("default").size() == 2
#     assert Queue("otherq").size() == 1

#     # Then flush redis!
#     worker.fixture_redis.flush()

#     # Assert the queues are empty.
#     assert Queue("default").size() == 0
#     assert Queue("otherq").size() == 0

#     res = worker.send_task(
#         "mrq.basetasks.cleaning.RequeueLostJobs", {}, block=True, queue="cleaning")

#     assert res["fetched"] == 3
#     assert res["requeued"] == 3

#     assert Queue("default").size() == 2
#     assert Queue("otherq").size() == 1

#     assert Queue("default").list_job_ids() == [str(job_id1), str(job_id2)]
#     assert Queue("otherq").list_job_ids() == [str(job_id3)]


# def test_interrupt_redis_started_jobs(worker):

#     worker.start(
#         queues="xxx", flags=" --config tests/fixtures/config-lostjobs.py")

#     worker.send_task("tests.tasks.general.Add", {
#                      "a": 41, "b": 1, "sleep": 10}, block=False, queue="xxx")
#     worker.send_task("tests.tasks.general.Add", {
#                      "a": 41, "b": 1, "sleep": 10}, block=False, queue="xxx")

#     time.sleep(3)

#     worker.stop(deps=False)

#     assert Queue("xxx").size() == 0
#     assert connections.redis.zcard(Queue.redis_key_started) == 2

#     worker.start(queues="default", start_deps=False, flush=False)

#     assert connections.redis.zcard(Queue.redis_key_started) == 2

#     res = worker.send_task("mrq.basetasks.cleaning.RequeueRedisStartedJobs", {
#         "timeout": 0
#     }, block=True, queue="default")

#     assert res["fetched"] == 2
#     assert res["requeued"] == 2

#     assert Queue("xxx").size() == 2
#     assert Queue("default").size() == 0
#     assert connections.redis.zcard(Queue.redis_key_started) == 0


def test_interrupt_maxjobs(worker):

    # The worker will stop after doing 5 jobs
    worker.start(flags="--max_jobs 5 --greenlets 2", queues="test1 default")

    worker.send_tasks("tests.tasks.general.Add", [
        {"a": i, "b": 1, "sleep": 0}
        for i in range(12)
    ], block=False)

    time.sleep(2)

    assert Queue("default").size() == 7


def test_worker_interrupt_after_max_time(worker):
    worker.start(flags="--greenlets=2 --max_time=2", queues="test1 default")

    task_ids = worker.send_tasks("tests.tasks.general.Add", [{"a": i, "b": 1, "sleep": 3} for i in range(5)],
                                 block=False)

    time.sleep(5)

    results = [get_job_result(task_id) for task_id in task_ids]

    queued_tasks = [result for result in results if result['status'] == "queued"]
    successful_tasks = [(i, result) for i, result in enumerate(results) if result['status'] == "success"]

    assert len(queued_tasks) == 3
    assert len(successful_tasks) == 2
    for i, result in successful_tasks:
        assert result['result'] == i + 1


def test_interrupt_maxconcurrency(worker):

    # The worker will raise a maxconcurrency on the second job
    worker.start(flags="--greenlets=2")

    job_ids = worker.send_tasks("tests.tasks.concurrency.LockedAdd", [
        {"a": i, "b": 1, "sleep": 2}
        for i in range(2)
    ], block=False)

    worker.wait_for_tasks_results(job_ids, accept_statuses=["success", "failed", "maxconcurrency"])
    job_statuses = [Job(job_id).fetch().data["status"] for job_id in job_ids]
    assert set(job_statuses) == set(["success", "maxconcurrency"])

    # the job concurrency key must be equal to 0
    last_job_id = worker.send_task(
        "tests.tasks.concurrency.LockedAdd",
        {"a": 1, "b": 1, "sleep": 2},
        block=False
    )

    last_job = Job(last_job_id).wait(poll_interval=0.01)
    assert last_job.get("status") == "success"

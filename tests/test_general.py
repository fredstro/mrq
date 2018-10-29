from future import standard_library
standard_library.install_aliases()
from builtins import str
from bson import ObjectId
import urllib.request, urllib.error, urllib.parse
import json
import time
from mrq.job import Job, get_job_result


def test_general_simple_task_one(worker):

    result = worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 1})

    assert result == 42

    time.sleep(0.5)

    db_workers = list(worker.mongodb_jobs.mrq_workers.find())
    assert len(db_workers) == 1
    worker_report = worker.get_report()
    assert worker_report["status"] in ["full", "wait", "spawn"]
    assert worker_report["done_jobs"] == 1

    # Test the HTTP admin API
    admin_worker = json.loads(urllib.request.urlopen("http://localhost:%s" % worker.admin_port).read().decode('utf-8'))

    assert admin_worker["_id"] == str(db_workers[0]["_id"])
    assert admin_worker["status"] in ["wait", "spawn"]

    # Stop the worker gracefully
    worker.stop(deps=False)

    db_jobs = list(worker.mongodb_jobs.mrq_jobs.find())
    assert len(db_jobs) == 1
    assert db_jobs[0]["result"] == 42
    assert db_jobs[0]["status"] == "success"
    assert db_jobs[0]["queue"] == "default"
    assert db_jobs[0]["worker"]
    assert db_jobs[0]["datestarted"]
    assert db_jobs[0]["dateupdated"]
    assert db_jobs[0]["totaltime"] > 1
    assert db_jobs[0]["_id"]
    assert db_jobs[0]["params"] == {"a": 41, "b": 1, "sleep": 1}
    assert db_jobs[0]["path"] == "tests.tasks.general.Add"
    assert db_jobs[0]["time"] < 0.5
    assert db_jobs[0]["switches"] >= 1

    from mrq.job import get_job_result
    assert get_job_result(db_jobs[0]["_id"]) == {"result": 42, "status": "success"}

    db_workers = list(worker.mongodb_jobs.mrq_workers.find())
    assert len(db_workers) == 1
    assert db_workers[0]["_id"] == db_jobs[0]["worker"]
    assert db_workers[0]["status"] == "stop"
    assert db_workers[0]["jobs"] == []
    assert db_workers[0]["done_jobs"] == 1
    assert db_workers[0]["config"]
    assert db_workers[0]["_id"]

    # Job logs
    db_logs = list(
        worker.mongodb_logs.mrq_logs.find({"job": db_jobs[0]["_id"]}))
    assert len(db_logs) == 1
    assert "adding" in db_logs[0]["logs"]

    # Worker logs
    # db_logs = list(
    #     worker.mongodb_logs.mrq_logs.find({"worker": db_workers[0]["_id"]}))
    # assert len(db_logs) >= 1

    worker.stop_deps()


def test_general_nologs(worker):

    worker.start(flags="--mongodb_logs=0")

    assert worker.send_task(
        "tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 1}
    ) == 42

    db_workers = list(worker.mongodb_jobs.mrq_workers.find())
    assert len(db_workers) == 1

    # Worker logs
    db_logs = list(
        worker.mongodb_logs.mrq_logs.find({"worker": db_workers[0]["_id"]}))
    assert len(db_logs) == 0


def test_general_simple_no_trace(worker):

    worker.start(trace=False)

    result = worker.send_task("tests.tasks.general.Add", {"a": 41, "b": 1})

    assert result == 42


def test_general_simple_task_multiple(worker):

    result = worker.send_tasks("tests.tasks.general.Add", [
        {"a": 41, "b": 1, "sleep": 1},
        {"a": 41, "b": 1, "sleep": 1},
        {"a": 40, "b": 1, "sleep": 1}
    ])

    assert result == [42, 42, 41]

    assert [x["result"] for x in worker.mongodb_jobs.mrq_jobs.find().sort(
        [["dateupdated", 1]])] == [42, 42, 41]


def test_general_requeue_order(worker):
    from mrq.job import Job

    jobids = worker.send_tasks("tests.tasks.general.Add", [
        {"a": 41, "b": 1, "sleep": 4},
        {"a": 42, "b": 1, "sleep": 1},
        {"a": 43, "b": 1, "sleep": 1}
    ], block=False)

    time.sleep(2)

    # We should be executing job1 now. Let's requeue job2, making it go to the end of the queue.
    Job(jobids[1]).requeue()

    worker.wait_for_idle()

    assert [x["result"] for x in worker.mongodb_jobs.mrq_jobs.find().sort(
        [["dateupdated", 1]])] == [42, 44, 43]


def test_general_simple_task_reverse(worker):

    worker.start(queues="default_reverse xtest test_timed_set", flags="--config tests/fixtures/config-raw1.py")

    result = worker.send_tasks("tests.tasks.general.Add", [
        {"a": 41, "b": 1, "sleep": 1},
        {"a": 41, "b": 1, "sleep": 1},
        {"a": 40, "b": 1, "sleep": 1}
    ])

    assert result == [42, 42, 41]

    assert [x["result"] for x in worker.mongodb_jobs.mrq_jobs.find().sort(
        [["dateupdated", 1]])] == [41, 42, 42]


def test_known_queues_lifecycle(worker):

    worker.start(
        queues="default_reverse xtest test_timed_set",
        flags="--config tests/fixtures/config-raw1.py --subqueues_refresh_interval=0.1"
    )
    time.sleep(1)
    worker.wait_for_idle()

    # Test known queues
    from mrq.queue import Queue, send_task, send_raw_tasks

    # Just watching queues doesn't add them to known ones.
    # BTW this doesn't read config from the worker, just db/redis.
    assert set(Queue.all_known()) == set()

    # Try queueing a task
    send_task("tests.tasks.general.Add", {"a": 41, "b": 1, "sleep": 1}, queue="x")

    jobs = list(worker.mongodb_jobs.mrq_jobs.find())
    assert len(jobs) == 1
    assert jobs[0]["queue"] == "x"

    assert set(Queue.all_known()) == set(["x"])

    Queue("x").empty()

    jobs = list(worker.mongodb_jobs.mrq_jobs.find())
    assert len(jobs) == 0
    assert set(Queue.all_known()) == set()

    all_known = worker.send_task("tests.tasks.general.QueueAllKnown", {}, queue="default")
    # Will get all from config
    assert len(all_known) > 0

    # Now add a job on a raw queue
    send_raw_tasks("test_raw/sub", ["a", "b", "c"])
    time.sleep(1)

    all_known_plus_sub = worker.send_task("tests.tasks.general.QueueAllKnown", {}, queue="default")
    assert set(all_known_plus_sub) == set(all_known).union(set(["test_raw/sub"]))

    # This behavious was removed in https://github.com/pricingassistant/mrq/commit/dcb7c954c998d0d8f32b799da0fb0aa11524e5b9
    # We might restore it if we find a way to improve performance
    # Queue("test_raw/sub").remove_raw_jobs(["a", "b", "c"])

    # all_known_plus_sub = worker.send_task("tests.tasks.general.QueueAllKnown", {}, queue="default")
    # assert set(all_known_plus_sub) == set(all_known)


def test_general_exception_status(worker):

    worker.send_task("tests.tasks.general.RaiseException", {
                     "message": "xyz"}, block=True, accept_statuses=["failed"])

    job1 = worker.mongodb_jobs.mrq_jobs.find_one()
    assert job1
    assert job1["exceptiontype"] == "Exception"
    assert job1["status"] == "failed"
    assert "raise" in job1["traceback"]
    assert "xyz" in job1["traceback"]


def test_general_task_whitelist(worker):

    worker.start(queues="default", flags="--task_whitelist tests.tasks.general.Add,tests.tasks.general.Square")

    job1 = worker.send_task("tests.tasks.general.Add", {"a": 41, "b": 1}, block=False)
    job2 = worker.send_task("tests.tasks.general.Square", {"n": 41}, block=False)
    job3 = worker.send_task("tests.tasks.general.GetTime", {}, block=False)

    time.sleep(3)

    res1 = get_job_result(job1)
    res2 = get_job_result(job2)
    res3 = get_job_result(job3)

    assert res1["status"] == "success"
    assert res2["status"] == "success"
    assert res3["status"] == "queued"


def test_general_task_blacklist(worker):

    worker.start(queues="default", flags="--task_blacklist tests.tasks.general.Add,tests.tasks.general.Square")

    job1 = worker.send_task("tests.tasks.general.Add", {"a": 41, "b": 1}, block=False)
    job2 = worker.send_task("tests.tasks.general.Square", {"n": 41}, block=False)
    job3 = worker.send_task("tests.tasks.general.GetTime", {}, block=False)

    time.sleep(3)

    res1 = get_job_result(job1)
    res2 = get_job_result(job2)
    res3 = get_job_result(job3)

    assert res1["status"] == "queued"
    assert res2["status"] == "queued"
    assert res3["status"] == "success"

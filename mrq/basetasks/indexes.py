from mrq.task import Task
from mrq.context import connections


class EnsureIndexes(Task):
    created_indexes = False

    def run(self, params):
        if self.created_indexes:
            return
        if connections.mongodb_logs:
            connections.mongodb_logs.mrq_logs.create_index(
                [("job", 1)], background=True)
            connections.mongodb_logs.mrq_logs.create_index(
                [("worker", 1)], background=True, sparse=True)

        connections.mongodb_jobs.mrq_workers.ensure_index(
            [("status", 1)], background=True)
        connections.mongodb_jobs.mrq_workers.create_index(
            [("datereported", 1)], background=True, expireAfterSeconds=3600)

        connections.mongodb_jobs.mrq_jobs.create_index(
            [("status", 1)], background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("path", 1)], background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("worker", 1)], background=True, sparse=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("queue", 1)], background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("dateexpires", 1)], sparse=True, background=True, expireAfterSeconds=0)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("dateretry", 1)], sparse=True, background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("datequeued", 1)], background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("queue", 1), ("status", 1), ("datequeued", 1), ("_id", 1)], background=True)
        connections.mongodb_jobs.mrq_jobs.create_index(
            [("status", 1), ("queue", 1), ("path", 1)], background=True)

        connections.mongodb_jobs.mrq_scheduled_jobs.create_index(
            [("hash", 1)], unique=True, background=False)

        connections.mongodb_jobs.mrq_agents.create_index(
            [("datereported", 1)], background=True)
        connections.mongodb_jobs.mrq_agents.create_index(
            [("dateexpires", 1)], background=True, expireAfterSeconds=0)
        connections.mongodb_jobs.mrq_agents.create_index(
            [("worker_group", 1)], background=True)
        self.created_indexes = True
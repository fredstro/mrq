import urlparse
import gevent
import gevent.pool
import re
import os
import signal
import datetime
import time
import socket
import traceback
import psutil
import redis as pyredis
from pymongo.mongo_client import MongoClient
from bson import ObjectId

from .job import Job
from .exceptions import JobTimeoutException, StopRequested

# greenletid => Job object
GREENLET_JOBS_REGISTRY = {}

WORKER = None


def get_current_job():
  return GREENLET_JOBS_REGISTRY.get(id(gevent.getcurrent()))


def get_current_worker():
  return WORKER


class Worker(object):

  # Allow easy overloading
  job_class = Job

  stop_signals = [signal.SIGINT, signal.SIGTERM]

  def __init__(self, config):

    #queues, pool_size=1, max_jobs=None, redis=None, mongodb_jobs=None, mongodb_logs=None, name=None):

    global WORKER
    WORKER = self

    self.config = config

    self.datestarted = datetime.datetime.utcnow()
    self.status = "init"
    self.queues = self.config["queues"]
    self.done_jobs = 0
    self.max_jobs = self.config["max_jobs"]

    self.process = psutil.Process(os.getpid())

    self.id = ObjectId()
    if config["name"]:
      self.name = self.config["name"]
    else:
      self.name = self.make_name()

    self.pool_size = self.config["pool_size"]

    from .logger import LogHandler
    self.log_handler = LogHandler(quiet=self.config["quiet"])
    self.log = self.log_handler.get_logger(worker=self.id)

    self.log.info("Starting Gevent pool with %s worker greenlets (+ 1 monitoring)" % self.pool_size)

    self.gevent_pool = gevent.pool.Pool(self.pool_size)

    # Keep references to main greenlets
    self.greenlets = {}

    self.connect_redis(self.config["redis"])

    self.mongodb_jobs = self.connect_mongodb("jobs", self.config["mongodb_jobs"])
    if self.config["mongodb_logs"] == self.config["mongodb_jobs"]:
      self.mongodb_logs = self.mongodb_jobs
    else:
      self.mongodb_logs = self.connect_mongodb("logs", self.config["mongodb_logs"])

    self.log_handler.set_collection(self.mongodb_logs.mrq_logs)

    self.profiler = None
    if self.config["profile"]:
      print "Starting profiler..."
      import cProfile
      self.profiler = cProfile.Profile()
      self.profiler.enable()

  def make_name(self):
    """ Generate a human-readable name for this worker. """
    return "%s.%s" % (socket.gethostname().split(".")[0], os.getpid())

  def connect_redis(self, redis):

    if type(redis) in [str, unicode]:

      urlparse.uses_netloc.append('redis')
      redis_url = urlparse.urlparse(redis)

      self.log.info("Connecting to Redis at %s..." % redis_url.hostname)

      redis_pool = pyredis.ConnectionPool(host=redis_url.hostname, port=redis_url.port, db=0, password=redis_url.password)

      self.redis = pyredis.StrictRedis(connection_pool=redis_pool)

    # Let's just assume we got a StrictRedis-like object!
    else:
      self.redis = redis

  def connect_mongodb(self, name, mongodb):

    if type(mongodb) in [str, unicode]:

      (mongoAuth, mongoUsername, mongoPassword, mongoHosts, mongoDbName) = re.match(
        "mongodb://((\w+):(\w+)@)?([\w\.:,-]+)/([\w-]+)", mongodb).groups()

      self.log.info("Connecting to MongoDB at %s..." % mongoHosts)

      db = MongoClient(mongoHosts)[mongoDbName]
      if mongoUsername:
        db.authenticate(mongoUsername, mongoPassword)

      return db

    # Let's just assume we got a MongoDB-like object!
    else:
      return mongodb

  def greenlet_monitoring(self):
    """ This greenlet always runs in background to update current status in MongoDB every 10 seconds.

    Caution: it might get delayed when doing long blocking operations.
     """

    while True:

      # print "Monitoring..."

      self.report_worker()
      self.flush_logs()
      time.sleep(1)

  def report_worker(self):

      greenlets = []

      for greenlet in self.gevent_pool:
        g = {}
        short_stack = []
        stack = traceback.format_stack(greenlet.gr_frame)
        for s in stack[1:]:
          if "/gevent/hub.py" in s:
            break
          short_stack.append(s)
        g["stack"] = short_stack

        job = GREENLET_JOBS_REGISTRY.get(id(greenlet))
        if job:
          if job.data:
            g["path"] = job.data["path"]
          g["datestarted"] = job.datestarted

        greenlets.append(g)

      cpu = self.process.get_cpu_times()

      whitelisted_config = [
        "max_jobs",
        "pool_size",
        "queues",
        "name"
      ]

      self.mongodb_logs.mrq_workers.update({
        "_id": ObjectId(self.id)
      }, {"$set": {
        "status": self.status,
        "registry_size": len(GREENLET_JOBS_REGISTRY),
        "config": {k: v for k, v in self.config.iteritems() if k in whitelisted_config},
        "done_jobs": self.done_jobs,
        "datestarted": self.datestarted,
        "datereported": datetime.datetime.utcnow(),
        "process": {
          "pid": self.process.pid,
          "cpu": {
            "user": cpu.user,
            "system": cpu.system,
            "percent": self.process.get_cpu_percent(0)
          },
          "mem": {
            "rss": self.process.get_memory_info().rss
          }
          # https://code.google.com/p/psutil/wiki/Documentation
          # get_open_files
          # get_connections
          # get_num_ctx_switches
          # get_num_fds
          # get_io_counters
          # get_nice
        },
        "jobs": greenlets
      }}, upsert=True, w=0)

  def flush_logs(self):
    self.log_handler.flush()

  def dequeue_jobs(self, max_jobs=1):

    self.log.debug("Fetching %s jobs from Redis" % max_jobs)

    jobs = []
    queue, job_id = self.redis.blpop(self.queues, 0)

    # From this point until job.fetch_and_start(), job is only local to this worker.
    # If we die here, job will be lost in redis without having been marked as "started".

    jobs.append(self.job_class(job_id, worker=self, queue=queue, start=True))

    # Bulk-fetch other jobs from that queue to fill the pool.
    if max_jobs > 1:

      with self.redis.pipeline(transaction=False) as pipe:
        for _ in range(max_jobs - 1):
          pipe.lpop(queue)
        job_ids = pipe.execute()

      jobs += [self.job_class(_job_id, worker=self, queue=queue, start=True)
               for _job_id in job_ids if _job_id]

    return jobs

  def work_loop(self):
    """Starts the work loop.

    """

    self.status = "started"

    self.greenlets["monitoring"] = gevent.spawn(self.greenlet_monitoring)

    self.install_signal_handlers()

    try:

      while True:

        while True:
          free_pool_slots = self.gevent_pool.free_count()
          if free_pool_slots > 0:
            break
          gevent.sleep(0)

        self.log.info('Listening on %s' % self.queues)

        jobs = self.dequeue_jobs(max_jobs=free_pool_slots)

        for job in jobs:

          self.gevent_pool.spawn(self.perform_job, job)

          self.done_jobs += 1

        if self.max_jobs and self.max_jobs >= self.done_jobs:
          self.log.info("Reached max_jobs=%s" % self.done_jobs)
          break

    except StopRequested:
      pass

    finally:

      self.log.debug("Joining the greenlet pool...")
      self.status = "stopping"

      self.gevent_pool.join(timeout=None, raise_error=False)
      self.log.debug("Joined.")

      self.greenlets["monitoring"].kill(block=True)
      self.log.debug("Monitoring greenlet killed.")

      if self.profiler:
        self.profiler.print_stats(sort="cumulative")

  def perform_job(self, job):
    """ Wraps a job.perform() call with timeout logic and exception handlers.

        This is the first call happening inside the greenlet.
    """

    GREENLET_JOBS_REGISTRY[id(gevent.getcurrent())] = job

    gevent_timeout = gevent.Timeout(job.timeout, JobTimeoutException(
      'Gevent Job exceeded maximum timeout  value (%d seconds).' % job.timeout
    ))

    gevent_timeout.start()

    try:
      job.perform()

    except job.retry_on_exceptions:
      job.retry()

    except JobTimeoutException:
      raise
      #self.handle_exception(job, *sys.exc_info())

    except Exception:
      raise
      #self.handle_exception(job, *sys.exc_info())

    finally:
      gevent_timeout.cancel()

      GREENLET_JOBS_REGISTRY[id(gevent.getcurrent())] = None

  def shutdown_graceful(self):
    """ Graceful shutdown: waits for all the jobs to finish. """

    self.log.info("Graceful shutdown...")
    raise StopRequested()

  def shutdown_now(self):
    """ Forced shutdown: interrupts all the jobs. """

    self.log.info("Forced shutdown...")
    self.status = "killing"

    self.gevent_pool.kill(block=True, timeout=2)

  def install_signal_handlers(self):
    """ Handle events like Ctrl-C from the command line. """
    def request_shutdown_now():  # signum, frame):
      self.shutdown_now()

    def request_shutdown_graceful():  # signum, frame):

      # Second time, shutdown now
      for s in self.stop_signals:
        gevent.signal(s, request_shutdown_now)

      self.shutdown_graceful()

    # First time, try to shutdown gracefully
    for s in self.stop_signals:
      gevent.signal(s, request_shutdown_graceful)

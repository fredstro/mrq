# Transient dependency treatment (WinCon #112)

Worker startup retries Mongo server-selection failures during queue discovery
and index creation with 1/2/4/8/10-second backoff for a two-minute window.
Authentication/configuration failures still fail immediately. Retry logs do not
include connection strings. This is pre-job startup work, not a retry wrapper
around arbitrary task bodies or the whole worker process.

The scheduler acquires its Redis lease explicitly: another worker owning it
is a deferred tick, not a fatal worker error. Lease expiry during release is
logged, with a minimum three-minute lease. This is not a heartbeat or an
exactly-once scheduler guarantee; measure long ticks and confirm only one leader
queues during a synthetic staging interruption.

Runtime Mongo failures during dequeue/scheduling still need separate treatment.
A blanket retry around `work_once` or `Scheduler.check` can duplicate partially
queued work or leave ambiguous `started` records after a lost write response;
raw queues can pop Redis payloads before Mongo persistence. Define durable
recovery/idempotency before changing those paths. These changes therefore only
partially treat #112. Verify dependency outage recovery and in-flight jobs in
staging, pin the reviewed commit in consumers, then deploy separately.

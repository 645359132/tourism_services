# Plan for validating 10,000 simultaneous online users

“10,000 online” is a concurrency target, not 10,000 requests per second. Before a test, record the
expected mix of connected-but-idle users, active HTTP users, and long-lived WebSockets. A starting
hypothesis for planning is 10,000 authenticated sessions, up to 2,000 concurrent WebSockets,
500 steady HTTP requests/s, and a 1,000 requests/s burst. These figures are test inputs to refine,
not measured capacity.

## Target topology

Use a production-like test environment rather than scaling the local SQLite result:

1. Put multiple stateless Uvicorn worker processes behind an L7 load balancer with WebSocket
   support, connection draining, timeouts longer than the client heartbeat, and per-route metrics.
2. Use PostgreSQL as the authoritative store. Put PgBouncer (transaction pooling) between workers
   and PostgreSQL, cap the sum of worker pools below the database connection budget, and monitor
   lock waits, deadlocks, transaction duration, replication lag, and slow queries.
3. Enable Redis coordination for cross-worker rate limits, reference caches, one-use WebSocket
   tickets, advisory claims, publisher leadership, and pub/sub fan-out. Use a replicated/managed
   Redis tier and set `REDIS_REQUIRED=true` for a capacity certification so a Redis outage fails
   closed instead of silently measuring process-local fallback behavior.
4. Keep SQL uniqueness constraints and atomic inventory updates authoritative. Redis locks reduce
   duplicate work but are not the source of truth for ticket, reservation, or shop inventory.
5. Move large immutable offline assets behind object storage and a CDN if their measured bandwidth
   becomes material; keep authorization-aware manifests and mutable sync state in the API.

An initial deployment candidate is 8 application replicas with 2 workers each. That is only a
starting point (about 625 online sessions per process and 125 WebSockets per process under the
planning mix). CPU, memory per socket, event-loop lag, and database pool telemetry must decide the
real replica count. For example, a pool of 10 plus overflow 5 across 16 processes can attempt 240
database connections, so PgBouncer and an explicit database connection budget are mandatory.

## Identity and data isolation

The local load seeder creates at most 10,000 deterministic tourist identities and refuses to run
in staging or production. For a dedicated test environment, either run it with `APP_ENV=test` or
provision equivalent synthetic identities through the environment's approved identity pipeline.
Never run the scenario against customer accounts or production inventory.

Every generator process needs a disjoint identity shard. Four 2,500-user shards use offsets 0,
2500, 5000, and 7500 with `TOURISM_LOAD_USER_COUNT=2500`. The allocator rejects a shard whose
offset plus count exceeds 10,000 and stops rather than reusing an identity. Keep the password in a
secret manager/environment injection, not command arguments or result files.

Seed inventory for the intended write volume and use a new database/schema for every comparable
run. The current Locust workload performs one ticket, reservation, and shop purchase per user;
10,000 users therefore require deliberately sized test inventory. Exhausted inventory is a valid
business result, but it must not be mistaken for an infrastructure failure or excluded after the
run.

## Staged test programme

### 1. Functional distributed gate

- Run migrations and idempotent seeds twice.
- Start at least two app replicas with PostgreSQL and Redis.
- Run the 46-check smoke through the load balancer.
- Verify a WebSocket ticket issued through one replica can be consumed only once through another,
  and that crowd, queue, and support events cross replica boundaries.
- Stop Redis once with `REDIS_REQUIRED=true` and confirm readiness/coordination-sensitive requests
  fail closed; repeat in an explicitly degraded environment and verify local fallback is visible.

### 2. HTTP ramp and soak

- 50 users for 5 minutes to validate data and dashboards.
- 250, 500, 1,000, and 2,500 active users for 10 minutes per step.
- Hold the first resource knee for 60 minutes, then run a 4-hour soak below that knee.
- Generate load from separate hosts. Synchronize clocks and retain Locust CSV, server metrics,
  PostgreSQL/Redis metrics, logs, deployment revision, configuration, and seed manifest.

Advance only while total unexpected failures stay below 1%, aggregate p95 stays below 750 ms,
list/read p95 stays below 300 ms, and inventory mutation p95 stays below 1,000 ms. HTTP 409 business
conflicts and 429 rate limits must be tagged separately and must match the planned inventory and
rate-limit model. These are provisional certification gates, not promises derived from the local
run.

### 3. Long-lived WebSocket ramp

The checked-in Locust scenario measures repeated handshake plus initial crowd snapshot exchanges;
it does not hold thousands of sockets open. Add a dedicated long-lived harness before claiming the
online target. Ramp 500, 2,000, 5,000, then 10,000 sockets, maintain representative subscriptions,
send heartbeats with jitter, and publish crowd/queue/support events at realistic rates.

At every step measure connection success, abnormal close codes, reconnect rate, publish-to-receive
p50/p95/p99, fan-out completeness, process RSS per connection, file/socket handles, Redis pub/sub
lag, and event-loop lag. A provisional gate is at least 99.9% successful connections, at least
99.9% expected-message delivery, under 1% abnormal closes, and publish-to-receive p95 below 1 s.

### 4. Failure and recovery

- Roll one app replica while sockets and writes are active; verify draining and bounded reconnects.
- Kill a Locust worker and prove its credential shard can be deliberately reclaimed for a new run.
- Restart/fail over Redis and PostgreSQL separately; verify ticket single-use semantics, idempotency,
  no oversell, and recovery time.
- Inject a slow database and a slow consumer; confirm backpressure, bounded queues, timeouts, and
  rate limits protect the service.
- Burst from steady state to 2x traffic, then return to steady state without a retry storm.

## Evidence required for a 10,000-online claim

Do not approve the claim from client-side success rate alone. Preserve:

- exact application revision, image digest, migrations, configuration, topology, and instance sizes;
- generated identity ranges and inventory budget, with no credentials;
- raw HTTP and WebSocket generator results plus percentile histograms;
- app CPU/RSS/event-loop lag, open sockets, restarts, and per-route errors;
- PostgreSQL connections, TPS, query latency, locks/deadlocks, I/O, and storage headroom;
- Redis CPU/memory/operations, pub/sub lag, evictions, connection count, and failover events;
- load-balancer connection counts, rejected handshakes, TLS time, and bytes transferred;
- reconciliation proving ticket, reservation, and shop inventory never oversold and idempotency
  produced no duplicate durable operations.

Only the highest stage meeting every gate for the full hold period is a defensible capacity result.
If a gate fails, report that stage as the current limit, preserve the evidence, fix the identified
bottleneck, and repeat from the preceding successful stage.

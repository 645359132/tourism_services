# Checkpoint 9 local capacity baseline

This directory records the measured local baseline for the Smart Tourism Service. It is a
repeatable engineering check, not a production capacity claim.

## Result

The run completed on 2026-09-04 (Asia/Shanghai) with real Uvicorn listeners and a separate
Locust process on loopback. Uvicorn was restarted between accelerated smoke verification and
the default-cadence measured workload.

| Measure | Observed |
|---|---:|
| Concurrent users | 5 |
| Spawn rate | 5 users/s |
| Requested duration | 30 s |
| Requests in the CSV summary | 320 |
| Failures | 0 (0.00%) |
| Throughput | 11.42 requests/s |
| Mean response time | 34.78 ms |
| p50 / p90 / p95 / p99 | 14 / 75 / 160 / 370 ms |
| Maximum response time | 808.20 ms |
| Crowd WebSocket exchanges | 27, all successful |

Locust's terminal summary included four requests which completed during graceful shutdown
(324 total at 11.30 requests/s). The machine-readable CSV writer had already taken its final
snapshot at 320 requests. The table above deliberately uses the checked-in CSV as the canonical
source. Both views reported zero failures; the CSV maximum was 808.20 ms.

Each of the five users logged in with a different seeded identity, then performed exactly one
ticket order/payment, experience reservation/confirmation, and shop cart/checkout/payment.
After those bounded writes, users browsed ticket, reservation, and shop lists and repeatedly
opened the crowd WebSocket long enough to receive its initial snapshot. This prevents shared
carts or idempotency keys from making the result artificially successful.

Raw evidence:

- [`baseline-5u-30s_stats.csv`](baseline-5u-30s_stats.csv): endpoint and aggregate statistics.
- [`baseline-5u-30s_stats_history.csv`](baseline-5u-30s_stats_history.csv): one-second samples.
- [`baseline-5u-30s_failures.csv`](baseline-5u-30s_failures.csv): header only; no failures.
- [`baseline-5u-30s_exceptions.csv`](baseline-5u-30s_exceptions.csv): header only; no exceptions.
- [`baseline-5u-30s_SHA256SUMS.txt`](baseline-5u-30s_SHA256SUMS.txt): hashes of the
  four raw CSV files from the accepted run.

The five-sample percentiles for write endpoints are descriptive only. In this run, the largest
individual observations were reservation confirmation at 808.20 ms, ticket order at 492.31 ms,
and login at 371.28 ms. A longer run is required before treating endpoint percentiles as stable.

## Environment and boundaries

- Windows 11 10.0.26200, AMD Ryzen 7 7735H (8 cores / 16 logical processors), 15.2 GiB RAM.
- Python 3.12.9 (project virtual environment), uv 0.8.14, Uvicorn 0.52.4, Locust 2.46.4.
- One Uvicorn process, local SQLite database, in-process coordination, no TLS or reverse proxy.
- The load generator and API shared the same host, so CPU contention is included while real
  network, load-balancer, and TLS latency are not.
- A separate ignored database was migrated from zero and seeded with ten load users. The 46-check
  acceptance smoke ran first with the demo tourist; the five Locust identities had no prior carts,
  orders, reservations, or refresh sessions.
- The smoke listener used 0.5-second crowd/queue publishers so it could prove later live events.
  Uvicorn was then restarted for the measured workload with the normal 30-second crowd and
  15-second queue publisher intervals.

Docker 29.1.3 and Compose 2.40.3 later ran the complete API + PostgreSQL + Redis topology on the
same machine. That companion run is recorded separately below so the original SQLite measurement
and the full-mode measurement remain distinguishable.

## PostgreSQL + Redis Compose companion run

On 2026-09-04, the API image was rebuilt and started with PostgreSQL 16, Redis 7, Redis-required
coordination, and two Uvicorn workers. PostgreSQL migrated transactionally from an empty database
to revision `20260901_0007`; a repeated upgrade was a no-op, `alembic check` found no drift, and
two further seed runs were idempotent. All three containers remained healthy, Redis returned PONG,
the API restart count stayed zero, and the contemporaneous preflight runner passed all 46 checks.

The same stack then ran the bounded five-user workload:

| Measure | Observed |
|---|---:|
| Concurrent users / duration | 5 / 30 s |
| Requests in the CSV summary | 319 |
| Failures | 0 (0.00%) |
| Throughput | 11.33 requests/s |
| Mean response time | 32.76 ms |
| p50 / p90 / p95 / p99 | 17 / 82 / 130 / 350 ms |
| Maximum response time | 367.80 ms |
| Crowd WebSocket exchanges | 30, all successful |

Locust's terminal summary included five requests completed after the CSV snapshot during graceful
shutdown: 324 requests, zero failures, and 11.29 requests/s. The checksummed CSV is the canonical
measurement. Each of five distinct load identities completed ticket order/payment, reservation/
confirmation, and cart/checkout/payment before entering the browse/WebSocket mix.

Compose evidence:

- [`compose-5u-30s_stats.csv`](compose-5u-30s_stats.csv)
- [`compose-5u-30s_stats_history.csv`](compose-5u-30s_stats_history.csv)
- [`compose-5u-30s_failures.csv`](compose-5u-30s_failures.csv)
- [`compose-5u-30s_exceptions.csv`](compose-5u-30s_exceptions.csv)
- [`compose-5u-30s_SHA256SUMS.txt`](compose-5u-30s_SHA256SUMS.txt)

The host already ran a Windows PostgreSQL service on port 5432, so Compose published its database
as `127.0.0.1:15432`; service-to-service traffic still used `postgres:5432`. Full reproduction and
PowerShell 5.1-compatible secret generation are in the
[acceptance guide](../testing/acceptance.md#4-docker-compose静态与运行时边界).

## Reproduction

Run commands from `server/`. Use a fresh, isolated database because the scenario intentionally
consumes inventory and creates durable orders. Supply the synthetic load password through the
environment; do not put it in shell history, source control, CSV prefixes, or reports.

```powershell
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite+aiosqlite:///./data/cp9-local.db'
$env:ENABLE_DEMO_ACCOUNTS = 'true'
$env:TOURISM_LOAD_USER_PASSWORD = '<local-only secret, at least 12 characters>'
uv run alembic upgrade head
uv run tourism-load-seed --count 10
```

Start the server in one terminal:

```powershell
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '0.5'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '0.5'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Prove the full REST/WebSocket acceptance path in another terminal:

```powershell
uv run tourism-smoke --base-url http://127.0.0.1:8765 --timeout 10
```

The current smoke is network-only and passes 49 checks: health, docs, capability metadata, tourist
registration, the immediately usable registered session, duplicate-username rejection, login,
ticket order/payment/QR and validation-window enforcement, reservation confirm/cancel, shop
checkout/payment, checkpoint 8 offline/sync/emergency/passport/green flows, a crowd initial frame
plus later publisher tick, a queue frame plus one-use ticket rejection, and tourist plus demo-bot
support messages verified again through REST persistence.

The 46-check labels above belong to the recorded performance snapshots. The current runner adds
three registration checks and passes 49; the stored request totals and latency percentiles remain
associated with their original CSV artifacts.

Stop the accelerated smoke listener. Restart Uvicorn with the normal publisher cadence:

```powershell
$env:CROWD_PUBLISH_INTERVAL_SECONDS = '30'
$env:QUEUE_PUBLISH_INTERVAL_SECONDS = '15'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Run the measured workload against that restarted listener:

```powershell
$env:TOURISM_LOAD_USER_COUNT = '10'
$env:TOURISM_LOAD_USER_OFFSET = '0'
uv run locust -f load/locustfile.py `
  --host http://127.0.0.1:8765 `
  --headless --users 5 --spawn-rate 5 --run-time 30s --stop-timeout 5 `
  --csv ../docs/performance/baseline-5u-30s --csv-full-history --only-summary
```

The allocator stops a virtual user if the configured identity pool is exhausted. It never wraps
around to another user's account. Missing ticket types, ticket inventory, experiences, sessions,
or product stock emits an explicit `SCENARIO` failure and stops that user, so an omitted write
cannot produce a green run. Re-running against the same database is valid for browsing but is not
a comparable inventory baseline; recreate the isolated database for a new measurement.

## Interpretation

The SQLite run establishes that the fallback scenario is feasible and observable; the Compose
companion additionally exercises PostgreSQL, Redis coordination, and two workers at the same small
load. Neither result establishes a service-level objective, saturation point, long-lived WebSocket
capacity, public-network behavior, or support for 10,000 simultaneous users. Those remain explicit
steps in the [10,000-online capacity plan](10k-capacity-plan.md).

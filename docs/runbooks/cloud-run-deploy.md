# Cloud Run Deploy — ADAM-EDU

> Runbook for deploying and operating the two Cloud Run services introduced in Issue #9.

---

## Services

| Service | Entrypoint | Min instances | Ingress |
|---|---|---|---|
| `public-api` | `shared.app:app` | 1 (avoids cold starts for users) | Public |
| `authoring-worker` | `shared.worker_app:worker_app` | 0 (scale to zero when idle) | Internal |

The `public-api` service handles all user-facing traffic (SPA, auth endpoints, authoring job intake).
The `authoring-worker` service processes async authoring jobs dispatched by Cloud Tasks — it has no public ingress.

Runtime guardrail: `--reload` is forbidden in non-development runtimes.
Production startup paths must never include `uvicorn ... --reload`.
La matriz runtime canonica (precedencia `APP_ENV` sobre `ENVIRONMENT`) vive en
`docs/runbooks/local-dev-auth.md`, seccion "Matriz runtime canonica".

---

## Database connection mode

| Environment | `ENVIRONMENT` value | Pool strategy |
|---|---|---|
| Local dev | `development` (default) | QueuePool (persistent, Docker Postgres on 5434) |
| Cloud Run | `production` | NullPool (1 conn/request, required for Supavisor transaction mode) |

**Why NullPool in production:** Supavisor in transaction mode does not maintain persistent connections.
A classic connection pool exhausts the allowed concurrent connections when Cloud Run scales horizontally.
NullPool creates and immediately releases a connection on every request — this is the correct behavior
for Cloud Run + Supavisor.

For autoscaling API/worker services, `DATABASE_URL` must target Supavisor transaction mode on port `6543`.

---

## Secret Manager → Environment variables

All secrets are stored in Google Secret Manager and mounted as environment variables via Cloud Run
secret bindings. **Never commit secret values to code, fixtures, or docs.**

| Secret Manager name | Environment variable | Services |
|---|---|---|
| `adam-database-url` | `DATABASE_URL` | api + worker |
| `adam-supabase-url` | `SUPABASE_URL` | api |
| `adam-supabase-anon-key` | `SUPABASE_ANON_KEY` | api |
| `adam-supabase-service-role-key` | `SUPABASE_SERVICE_ROLE_KEY` | api + worker |
| `adam-supabase-jwt-secret` | `SUPABASE_JWT_SECRET` | api (dev fallback only) |
| `adam-gemini-api-key` | `GEMINI_API_KEY` | worker |
| `adam-cloud-tasks-sa` | `CLOUD_TASKS_SERVICE_ACCOUNT` | worker |
| `adam-cloud-tasks-audience` | `CLOUD_TASKS_AUDIENCE` | worker |

Additionally, set these non-secret environment variables directly in the Cloud Run service config:

```
ENVIRONMENT=production
CORS_ALLOWED_ORIGIN=https://your-domain.com   # public-api only
```

---

## OIDC validation for authoring-worker

Cloud Tasks attaches an OIDC Bearer token to every request it dispatches.
The `authoring-worker` validates this token before executing any job.

**Required configuration (worker service):**
- `CLOUD_TASKS_SERVICE_ACCOUNT`: the service account email Cloud Tasks uses to sign tokens
  (e.g. `adam-tasks-invoker@PROJECT_ID.iam.gserviceaccount.com`)
- `CLOUD_TASKS_AUDIENCE`: the Cloud Run URL of the worker service
  (e.g. `https://authoring-worker-HASH-uc.a.run.app`)

**If either variable is unset:** OIDC validation is skipped and a WARNING is emitted to logs.
This is intentional for local development. It must **not** be unset in production.

**Token validation logic:**
1. Fetch Google OIDC public keys from `https://www.googleapis.com/oauth2/v3/certs` (cached 5 min).
2. Verify RS256 signature, expiry, and audience claim.
3. Assert `email` claim equals `CLOUD_TASKS_SERVICE_ACCOUNT`.
4. If Google's JWKS endpoint is unreachable → 503 (Cloud Tasks retries automatically).

---

## Minimum Cloud Run configuration

### public-api

```yaml
service: public-api
image: gcr.io/PROJECT_ID/adam-public-api:TAG
minInstances: 1
maxInstances: 10
concurrency: 80
memory: 512Mi
cpu: 1
ingress: all
```

### authoring-worker

```yaml
service: authoring-worker
image: gcr.io/PROJECT_ID/adam-authoring-worker:TAG
minInstances: 0
maxInstances: 5
concurrency: 10          # LangGraph jobs are CPU-heavy
memory: 2Gi              # LLM inference buffers
cpu: 2
ingress: internal        # Only Cloud Tasks can reach this service
timeout: 3600            # Long-running authoring jobs
```

**Cold start notes:**
- `public-api` min-instances=1 eliminates cold starts for interactive users.
- `authoring-worker` min-instances=0 is acceptable — Cloud Tasks retries on cold start timeout.
- Expected worker cold start: 15–30s (LangGraph + Gemini client initialization).

---

## Rate Limiting Strategy

**Estado actual (Issue #46):** Diferido — ver TODO-005 en `TODOS.md`.

`public-api` usa `maxInstances: 10`. Rate limiting in-memory (`slowapi`) daría contadores
independientes por instancia — hasta 10× el límite configurado sin protección real.

**Trigger para implementar:**
- Aprovisionar Cloud Memorystore (Redis) en el proyecto GCP, **o**
- Reducir `maxInstances` a 1 en `public-api` (permite `slowapi` in-memory)

**Límites target cuando se implemente:**

| Endpoint | Límite | Dimensión |
|---|---|---|
| `POST /api/invites/resolve` | 10 req/min | por IP |
| `POST /api/invites/redeem` | 5 req/min | por IP |
| `POST /api/auth/activate/password` | 5 req/min | por IP |
| `POST /api/auth/activate/oauth/complete` | 10 req/min | por IP |
| `POST /api/auth/change-password` | 3 req/min | por auth_user_id |

**Dependencias de implementación:** `fastapi-limiter>=0.1.6` + `redis>=5.0` en `backend/pyproject.toml`.

---

## Cloud Monitoring — minimum alert policies

### Issue #109 emitted metrics (log-based)

| Metric | Expected source | Notes |
|---|---|---|
| `db_session_acquire_latency_ms` | `public-api` critical endpoints | Use p50/p95/p99 dashboards |
| `db_backpressure_503_total` | `public-api` critical endpoints | Tag by endpoint + detail code |
| `db_timeout_total` | `public-api` critical endpoints | Timeout-specific counter |
| `auth_me_latency_ms` | `GET /api/auth/me` | Auth profile latency |
| `progress_snapshot_reads_total` | `GET /api/authoring/jobs/{job_id}/progress` | Progress read volume |

### Alerts

| Alert | Threshold | Rationale |
|---|---|---|
| Auth failures | `5xx on /api/auth/*` > 5/min | Detects brute-force or misconfiguration |
| Global 5xx | > 10/min on public-api | Catches deployment regressions |
| Latency p95 | > 3s on public-api | Tracks interactive response quality |
| Sustained DB backpressure | `db_backpressure_503_total` >= 20 in 5m | Detects saturation affecting user paths |
| DB timeout presence | `db_timeout_total` > 0 for 10m | Detects degraded DB behavior in active window |
| Cloud Tasks queue depth | > 50 pending tasks | Detects worker backlog |
| OIDC failures | `detail=invalid_oidc_token` > 3/min in worker logs | Detects unauthorized invocation attempts |
| JWKS unavailable | `detail=jwks_unavailable` in worker logs | Google OIDC endpoint health |

Detail code interpretation for Issue #109:
- `db_saturated`: fail-fast admission guard or connection saturation triggered; clients should back off using `Retry-After`.
- `db_timeout`: statement/lock timeout or operational timeout path; investigate slow queries/locks.

Log-based alerts should filter on the structured fields `metric_name`, `metric_value`, and `detail`/`detail_code`.

---

## Rollback procedure

1. **Worker fails after deploy:** `public-api` continues serving users normally.
   Jobs remain in `pending` state and will be retried by Cloud Tasks once the worker is healthy.
   No data loss. Rollback the worker image, jobs resume automatically.

2. **public-api fails after deploy:** Roll back to the previous revision via:
   ```bash
   gcloud run services update-traffic public-api \
     --to-revisions=PREVIOUS_REVISION=100 \
     --region=REGION
   ```

3. **Database migration rollback:** No migrations in Issue #9. NullPool is a connection strategy
   change only — reverting `ENVIRONMENT=production` to `development` restores classic pooling.

4. **Issue #109 resilience rollback knobs:** if saturation handling is too aggressive, adjust env vars
  in the last healthy Cloud Run revision and redeploy gradually:
  - `DB_STATEMENT_TIMEOUT_MS`
  - `DB_LOCK_TIMEOUT_MS`
  - `DB_CRITICAL_ENDPOINT_BUDGET`
  - `DB_RETRY_AFTER_SECONDS`

---

## Local verification commands

```bash
# Verify NullPool is selected in production mode
cd backend
ENVIRONMENT=production uv run python -c \
  "from shared.database import engine; print(engine.pool.__class__.__name__)"
# Expected: NullPool

# Verify QueuePool in development mode
ENVIRONMENT=development uv run python -c \
  "from shared.database import engine; print(engine.pool.__class__.__name__)"
# Expected: QueuePool

# Start worker locally (OIDC skipped — no SA configured)
uv run uvicorn shared.worker_app:worker_app --port 8081 &
curl http://localhost:8081/healthz
# Expected: {"status":"ok"}

# Verify OIDC guard fires with SA set
CLOUD_TASKS_SERVICE_ACCOUNT=test@test.iam.gserviceaccount.com \
CLOUD_TASKS_AUDIENCE=http://localhost:8081 \
uv run uvicorn shared.worker_app:worker_app --port 8082 &
curl -X POST http://localhost:8082/api/internal/tasks/authoring_step \
  -H "Content-Type: application/json" \
  -d '{"job_id":"x","idempotency_key":"k"}'
# Expected: 401 {"detail":"missing_oidc_token"}
```

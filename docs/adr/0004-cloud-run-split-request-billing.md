# ADR 0004: Split Cloud Run public-api / authoring-worker con facturación por request

- Status: Accepted
- Date: 2026-07-01
- Supersedes: la nota de ADR 0001 "El split `public-api` / `authoring-worker` queda despues, no antes" — este ADR es ese "después".
- Relación: activa la infraestructura dormida del Issue #9 (`shared/worker_app.py`, `shared/internal_tasks.py`, runbook `docs/runbooks/cloud-run-deploy.md`).

## Summary

Con 4-5 usuarios de bajo uso, Cloud Run cobraba ~US$200/mes (luego ~US$99 tras el
right-size del PR #564). La causa estructural: los jobs de authoring corren in-process
como background tasks, lo que obliga a `public-api` a usar facturación por instancia
(`--no-cpu-throttling`), y el goteo de tráfico 24/7 (bots escaneando el dominio público +
refetch de dashboards) mantiene la instancia facturando ~21 h/día aunque esté ociosa.

Se separa la ejecución de jobs a un segundo servicio Cloud Run (`authoring-worker`, misma
imagen) despachado vía Cloud Tasks, y `public-api` pasa a **facturación por request**
(instancias warm-idle gratis). Costo esperado: ~US$5-15/mes, escalando con el uso real.

## Context

- El intake (`POST /api/authoring/jobs`), el retry y el regenerate-notebook ejecutaban el
  job con `BackgroundTasks.add_task` en el proceso del API. Bajo facturación por request,
  Cloud Run le quita la CPU al proceso al terminar el request → los jobs se colgarían.
- El Issue #9 ya dejó construido y testeado el lado consumidor: `shared/worker_app.py`
  (FastAPI que expone SOLO `/api/internal/tasks/authoring_step` + `/healthz`) y
  `shared/internal_tasks.py` (validación OIDC de Cloud Tasks + barrera de idempotencia +
  `await AuthoringService.run_job(job_id)` INLINE, sosteniendo el request abierto durante
  todo el job). Faltaba únicamente el productor.
- Progreso y datos siguen 100% Supabase-native (Postgres + Realtime `postgres_changes`).
  Este ADR NO toca el camino de progreso; Cloud Tasks es solo el despacho del job.

## Decision

1. **Productor** `shared/job_dispatch.py`: `dispatch_authoring_job(...)` con el setting
   `AUTHORING_DISPATCH` (`inline` default | `cloud_tasks`). `inline` = comportamiento
   pre-ADR byte-idéntico (kill-switch). `cloud_tasks` = enqueue vía la REST API de Cloud
   Tasks con httpx + token del metadata server (cero dependencias nuevas), OIDC token
   firmado por `adam-run@` y `dispatchDeadline=1800s`. Un fallo del enqueue propaga error
   y el job queda `pending` (retryable); nunca hay fallback inline silencioso (bajo
   facturación por request un job inline se colgaría — peor que un error visible).
2. **Handler**: `InternalTaskPayload` gana `kind: "run" | "regenerate_notebook"` (default
   `"run"`, back-compat). `regenerate_notebook` aplica a jobs COMPLETED, así que salta la
   barrera de estados de run y descarga el servicio sync a un thread. La barrera existente
   ya soportaba el retry (`failed_resumable` no está bloqueado).
3. **Topología de billing**:
   - `authoring-worker`: misma imagen, `uvicorn shared.worker_app:worker_app`,
     `--no-cpu-throttling` (LOAD-BEARING: si Cloud Tasks suelta la conexión en su deadline
     de 30 min, la corutina sigue a CPU plena hasta el `GRAPH_EXECUTION_TIMEOUT_SECONDS`
     de 1900s y persiste un estado terminal limpio), `min-instances=0`, `max-instances=2`,
     `concurrency=2`, 2 vCPU/4Gi, `--no-allow-unauthenticated` (IAM: solo `adam-run@`
     invoker) + validación OIDC a nivel de aplicación (belt and suspenders).
   - `public-api`: `--cpu-throttling` (facturación por request), `min-instances=0`. El
     goteo de bots pasa de costo a beneficio: mantiene la instancia warm gratis.
4. **Infra**: cola `adam-authoring-jobs` (us-west1, max-attempts acotado), API
   `cloudtasks.googleapis.com`, IAM: `adam-run@` = `cloudtasks.enqueuer` +
   `iam.serviceAccountUser` sobre sí misma (mint del OIDC) + `run.invoker` sobre el worker.
   URLs determinísticas (`https://authoring-worker-1039937714231.us-west1.run.app`).

## Consequences

- Cloud Run pasa a costo proporcional al uso real (~US$2-10/mes de worker + ~US$0 del API
  dentro del free tier de request-billing). La promesa serverless se cumple.
- **Regla operativa nueva:** `AUTHORING_DISPATCH=cloud_tasks` y `--cpu-throttling` en
  `public-api` van SIEMPRE juntos, igual que `inline` + `--no-cpu-throttling`. Un estado
  mixto (`inline` + cpu-throttling) cuelga generaciones silenciosamente.
- Rollback total sin redeploy: `gcloud run services update public-api
  --update-env-vars=AUTHORING_DISPATCH=inline --no-cpu-throttling` (y opcionalmente apagar
  el worker). El código inline queda intacto como camino de dev/local/tests.
- Retries: Cloud Tasks reintenta entregas fallidas (worker frío, 5xx); la barrera de
  idempotencia evita el doble procesamiento; un job caído queda `failed_resumable` y el
  retry del teacher reanuda desde los checkpoints durables (resume ya existente).
- Cola tail: un job > 30 min pierde su conexión de Cloud Tasks pero termina igual (CPU
  siempre asignada en el worker); la re-entrega choca con la barrera (`processing` →
  bypassed 200) y no duplica trabajo.
- El deploy de CI publica dos servicios desde la misma imagen; el worker se despliega
  primero para que un `public-api` ya flippeado nunca despache a un worker viejo.

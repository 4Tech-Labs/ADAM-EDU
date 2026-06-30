# Despliegue de ADAM-EDU (producción)

Guía operativa del despliegue **real** en producción. Refleja la infraestructura
viva (no la del runbook histórico `docs/runbooks/cloud-run-deploy.md`, que describe
un diseño de dos servicios que hoy NO se usa).

---

## 1. Resumen / arquitectura

- **Un solo servicio** de Cloud Run: `public-api`. Sirve el SPA (frontend) **y** la
  API (FastAPI) desde la **misma imagen** y el **mismo origen**.
- La generación de casos corre **in-process** dentro de `public-api` (FastAPI
  `BackgroundTasks`) — no hay worker ni Cloud Tasks productor en el código.
- El frontend se compila **dentro** de la imagen (multi-stage Docker) y se sirve en
  la **raíz** del dominio (`/`).

```
Navegador ──HTTPS──> adamcampus.com ──> Cloud Run (public-api)
                                          ├─ /            -> SPA (React)
                                          ├─ /api/*       -> FastAPI
                                          └─ /health      -> healthcheck
        Supabase: Auth (JWT/JWKS) + Postgres (Supavisor :6543) + Realtime
        Gemini: generación de casos (in-process)
```

---

## 2. Coordenadas

| Recurso | Valor |
|---|---|
| GCP project | `gen-lang-client-0145484488` |
| Región | `us-west1` |
| Servicio Cloud Run | `public-api` |
| Imagen (Artifact Registry) | `us-west1-docker.pkg.dev/gen-lang-client-0145484488/adam-edu/public-api` |
| SA runtime (corre el servicio) | `adam-run@gen-lang-client-0145484488.iam.gserviceaccount.com` |
| SA deployer (CI) | `github-deployer@gen-lang-client-0145484488.iam.gserviceaccount.com` |
| Supabase project ref | `aoauxftghxujeduutbev` (región AWS us-west-2) |
| Dominio | `adamcampus.com` (registrado en **Hostinger**) |
| Repo GitHub | `4Tech-Labs/ADAM-EDU` |

---

## 3. Cómo desplegar (día a día)

El despliegue se dispara con un **push a la rama `deploy`** (no a `main`).

```bash
git checkout deploy
git merge main      # trae lo último de main
git push            # -> dispara el CI/CD: tests -> build -> deploy
```

- Tu equipo trabaja normal: `feature` → PR → `main`. **Eso NO despliega nada.**
- Solo cuando actualizas `deploy` se publica. Es el "botón de producción".
- El job de deploy **está gateado por los tests**: si algún test falla, no despliega.

> Si GitHub dice "branch out-of-date" al mergear un PR, dale **"Update branch"** y
> espera el CI verde (es la regla de "rama al día" del repo).

---

## 4. Cómo funciona el CI/CD

Definido en `.github/workflows/ci.yml`:

- **Tests** (siempre, en push a `main`/`deploy` y en PRs): `backend-test`,
  `backend-typecheck`, `frontend-lint`, `frontend-build`, `frontend-test`.
- **Job `deploy`** (solo en push a `deploy`, `if: github.ref == 'refs/heads/deploy'`):
  `needs` los 5 tests → si pasan, construye la imagen en el runner (`docker build`)
  con los `--build-arg VITE_*`, la sube a Artifact Registry y hace `gcloud run deploy`.
- **Autenticación sin llaves (Workload Identity Federation):** GitHub se autentica
  con GCP por identidad federada — **no hay ningún secret de GCP guardado en GitHub**.
  - Pool: `github-pool`, provider: `github`.
  - Condición de confianza: solo `repository == 4Tech-Labs/ADAM-EDU` **y**
    `ref == refs/heads/deploy`.
  - El deployer (`github-deployer`) tiene permisos mínimos: `run.admin`,
    `artifactregistry.writer` y `serviceAccountUser` solo sobre `adam-run`.
- Las GitHub Actions están **pineadas a SHA** (no a tags mutables) por seguridad de
  cadena de suministro. Dependabot mantiene los SHAs al día.

Config de escalado: `min-instances=0` (escala a cero → sin costo en reposo),
`--no-cpu-throttling` (CPU siempre asignada mientras la instancia vive, necesario
porque la generación corre in-process), `2 vCPU / 2Gi`, `timeout=3600`.

---

## 5. Variables de entorno y secretos

Los **secretos** viven SOLO en **Google Secret Manager** y se referencian por
**nombre** en el deploy (`--set-secrets`). Nunca en GitHub ni en el código.

| Secreto (Secret Manager) | Variable en runtime | Contenido |
|---|---|---|
| `adam-database-url` | `DATABASE_URL` | DSN de Supabase **Supavisor `:6543`** (transaction mode), esquema **`postgresql+psycopg://`**. Ej: `postgresql+psycopg://USER:PASS@HOST:6543/postgres?sslmode=require` |
| `adam-gemini-api-key` | `GEMINI_API_KEY` | API key de Gemini |
| `adam-supabase-service-role-key` | `SUPABASE_SERVICE_ROLE_KEY` | service_role de Supabase (backend-only) |

Variables NO secretas (en `--set-env-vars` del workflow): `ENVIRONMENT=production`,
`SUPABASE_URL`, `CORS_ALLOWED_ORIGIN=https://adamcampus.com`.

Variables `VITE_*` (se **hornean** en el build del frontend, son públicas):
`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (anon = pública por diseño),
`VITE_AUTH_CALLBACK_URL=https://adamcampus.com/auth/callback`. Están en el job
`deploy` de `ci.yml`.

### Rotar un secreto (2 pasos)

```bash
# 1) Nueva versión del valor en Secret Manager
printf '%s' 'NUEVO_VALOR' | gcloud secrets versions add adam-<nombre> --data-file=-
# 2) Redesplegar para que Cloud Run relea ':latest'
#    (un push a deploy, o un update manual:)
gcloud run services update public-api --region=us-west1
```

> Cambiar el valor en Secret Manager **no** actualiza la app sola: hay que
> redesplegar (paso 2). GitHub no interviene en esto.

---

## 6. Dominio (`adamcampus.com`)

- Registrado en **Hostinger** (el DNS se administra ahí: hPanel → Dominios → Zona DNS).
- Mapeado a Cloud Run con `gcloud beta run domain-mappings` + **SSL gestionado por Google**.
- La app se sirve en la **raíz** (`https://adamcampus.com`, sin `/app`).
- **Registros DNS en Hostinger** (nombre `@`): 4× **A** (`216.239.32/34/36/38.21`) +
  4× **AAAA** (`2001:4860:4802:32/34/36/38::15`) + el **TXT** de
  `google-site-verification` (no borrar) + CNAME `www`.
- La propiedad del dominio está verificada en Google Search Console.

### Supabase Auth (URL Configuration)

- **Site URL:** `https://adamcampus.com`
- **Redirect URLs:** `https://adamcampus.com/**`

### Añadir `www` (opcional, hoy no mapeado)

Mapear `www.adamcampus.com` como un segundo `domain-mapping` y añadir su registro DNS.

---

## 7. Onboarding de usuarios

El alta NO es registro abierto: cada usuario necesita **3 filas** en la BD de la app
(además de existir en Supabase Auth):

1. `profiles` (perfil), 2. `memberships` (rol + universidad), 3. la fila puente
**legacy `users`** (`shared.models.User`). Sin la #3, `GET /api/teacher/cases`
devuelve `500 legacy_bridge_missing`.

El flujo de **activación por invitación** crea las tres atómicamente. Para sembrar
una base de desarrollo coherente (universidad + cuentas + cursos) existe
`scripts/seed_dev.py` (idempotente). Requiere `DATABASE_URL` (`:6543`),
`SUPABASE_SERVICE_ROLE_KEY` y `PYTHONPATH=backend/src`.

---

## 8. Gotchas conocidos

- **`DATABASE_URL` debe usar el puerto `:6543`** (Supavisor transaction mode) **y el
  esquema `postgresql+psycopg://`** (el backend solo trae `psycopg` v3; un
  `postgresql://` a secas resuelve a psycopg2 → `ModuleNotFoundError` al importar). En
  `ENVIRONMENT=production` el código además valida el `:6543` al importar y hace
  crash-loop si no. Ej: `postgresql+psycopg://USER:PASS@HOST:6543/postgres?sslmode=require`.
- **`SUPABASE_JWT_SECRET` debe quedar VACÍA** en producción (se verifica por JWKS).
- **`SUPABASE_ANON_KEY` no es variable de backend** — solo del build del frontend
  (`VITE_SUPABASE_ANON_KEY`).
- **Frontend usa pnpm** (no npm). El `Dockerfile` (etapa `frontend-builder`) usa
  **`node:22-alpine`**: pnpm 11 requiere Node ≥ 22.13 (usa `node:sqlite`).
- **El SPA se monta en `/`** en `app.py` y esa línea **debe quedar al final** (las
  rutas `/api/*` y `/health` se registran antes y tienen precedencia).
- Migraciones de esquema: `uv run --directory backend alembic upgrade head` contra
  la BD `:6543`, **antes** de servir tráfico nuevo.

---

## 9. Verificación post-deploy (smoke test)

```bash
curl -s https://adamcampus.com/health           # {"status":"ok",...}
curl -s -o /dev/null -w "%{http_code}\n" https://adamcampus.com/        # 200 (SPA)
curl -s -o /dev/null -w "%{http_code}\n" https://adamcampus.com/api/auth/me  # 401
```

---

## 10. Rollback

Cloud Run versiona por revisión:

```bash
gcloud run revisions list --service=public-api --region=us-west1
gcloud run services update-traffic public-api --region=us-west1 \
  --to-revisions=REVISION_ANTERIOR=100
```

Para revertir el CI/CD a un estado previo del código: revertir el commit en `deploy`
y push (vuelve a desplegar la versión buena).

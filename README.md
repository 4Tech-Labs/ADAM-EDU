## ADAM EDU v8.0

ADAM EDU, en este corte, es un Teacher Authoring + Preview MVP. El repositorio publica el flujo docente que ya funciona: sugerencias para el formulario, generacion asincrona del caso con LangGraph, timeline por SSE y preview final para el profesor.

No incluye runtime de estudiante, super admin, auth real ni despliegue cloud endurecido. Esos frentes quedan fuera del alcance de esta subida para mantener el repo pequeno, honesto y estable.

Este repositorio evoluciona hoy como `ADAM-EDU`. El proyecto deriva del quickstart original de Gemini/LangGraph y conserva esa procedencia para fines de atribucion y trazabilidad, pero su desarrollo activo, gobernanza y flujo de colaboracion viven ya en esta linea de producto.

## Working Agreement

Mientras el repo opere sin enforcement completo de branch protection, `main` se trata como rama protegida por acuerdo operativo:

- nadie empuja directo a `main`
- todo cambio entra por pull request
- un PR solo se mergea con los 5 checks de CI en verde
- el merge operativo estandar es `Squash and merge`

La referencia viva para estas reglas esta en `CONTRIBUTING.md` y `docs/repo-governance.md`.

## Alcance actual

- `backend/src/case_generator/`: grafo LangGraph, prompts, schemas y servicios de authoring.
- `backend/src/shared/`: FastAPI app, DB, modelos, progress bus y contratos compartidos que siguen sosteniendo el flujo docente.
- `frontend/`: builder del profesor y preview editorial del caso generado.

La zona funcional principal del generador vive en `backend/src/case_generator/` y se mantiene congelada en este corte.

## Mapa de la raiz

- `docker-compose.yml`: stack local de desarrollo. Levanta la base PostgreSQL del proyecto y deja listo el entorno local base.
- `Dockerfile`: build contenedorizado del stack publicado. Se conserva para empaquetado del backend con el frontend compilado.
- `Makefile`: atajos opcionales para desarrollo en entornos Unix-like. Es conveniencia local, no la ruta principal de trabajo en Windows.
- `docs/archive/MASTER_AUDIT_PLAN.md`: auditoria historica archivada. Se conserva como referencia, pero ya no gobierna el alcance operativo del repo.

### Root hygiene

La raiz del repo se mantiene minima y operativa. Artefactos locales como `.claude/`, `.vscode/`, `.mypy_cache/` y `.python-version` no forman parte del repo publicado y no deben usarse como documentacion del proyecto.

## Mapa del backend

- `backend/src/case_generator/`: dominio funcional del producto. Aqui vive la logica de negocio del authoring, el grafo LangGraph, los prompts, adapters y servicios del generador de casos.
- `backend/src/shared/`: capa comun de app e infraestructura del MVP docente. Aqui viven FastAPI, base de datos, ORM, progress bus SSE, sanitizacion y contratos de soporte usados por el flujo docente.
- `backend/tests/`: validacion del backend docente. `tests/integration/` cubre validacion live del flujo/grafo y `tests/validation/` cubre shape y adapters.
- `backend/alembic/`: trazabilidad del esquema y migraciones historicas del backend.

`backend/src/shared/` tambien conserva modelos y schemas historicos retenidos por continuidad de base de datos y de contratos internos. Se mantienen en este corte aunque el repo publicado sea teacher-only.

### Naming freeze

En este corte no se renombran carpetas del backend.

- `case_generator` queda congelado porque es el nucleo funcional probado del repo.
- `shared` se conserva por estabilidad aunque sea un nombre generico.
- Cualquier rename futuro debe abrirse como refactor dedicado, no mezclado con el cierre de esta fase.

### Backend freeze zone

En limpiezas cosmeticas de esta fase no tocar:

- `backend/src/case_generator/graph.py`
- `backend/src/case_generator/prompts.py`

El endpoint interno `/api/internal/tasks/authoring_step` se conserva como seam de orquestacion interna/local. No implica que este repo publique ya un perimetro cloud endurecido.

## Mapa del frontend

- `frontend/src/app/`: shell del frontend. Aqui viven router, entrypoint, layout base y estilos globales.
- `frontend/src/features/teacher-authoring/`: flujo docente real. Contiene formulario, submit del job, SSE, timeline y estados del authoring.
- `frontend/src/features/case-preview/`: preview editorial del caso generado, incluyendo renderers y modulos `M1..M6`.
- `frontend/src/shared/`: piezas transversales del MVP. Aqui viven cliente API, tipos compartidos, header, toast, utilidades y primitives UI.

### Frontend naming freeze

En este corte no se renombran carpetas del frontend.

- `app`, `teacher-authoring`, `case-preview` y `shared` quedan congeladas como convencion estable del MVP.
- No reabrir carpetas top-level genericas como `components`, `pages`, `hooks`, `helpers`, `common` o `misc`.
- Si aparece nueva logica de producto, debe abrirse como feature explicita y no dentro de `shared/`.

## Flujo del MVP docente

1. `POST /api/suggest` ayuda a completar escenario y tecnicas del formulario.
2. `POST /api/authoring/jobs` crea `Assignment` + `AuthoringJob`.
3. `AuthoringService.run_job()` ejecuta el grafo y persiste el resultado.
4. `GET /api/authoring/jobs/{job_id}/progress` emite progreso por SSE.
5. `GET /api/authoring/jobs/{job_id}` permite polling del job.
6. `GET /api/authoring/jobs/{job_id}/result` devuelve el resultado persistido para preview.

El frontend usa ese flujo para renderizar el timeline y el `CasePreview` del profesor.

## Setup local

El flujo recomendado para contributors es:

1. levantar solo PostgreSQL con Docker
2. correr backend y frontend localmente

Ese flujo da mejor feedback para desarrollo diario, evita rebuilds del contenedor en cada cambio y deja el entorno mas facil de depurar.

### Prerrequisitos

- Docker Desktop o Docker Engine con Compose
- Python 3.12
- `uv`
- Node.js 22 + npm

### Opcion A: desarrollo recomendado (PostgreSQL en Docker, app local)

#### 1. Levantar solo PostgreSQL

Ejecuta esto desde la raiz del repo, no desde `backend/`:

```powershell
docker compose up -d adam-edu-postgres
```

Con el `docker-compose.yml` actual, los defaults locales quedan asi:

- host: `localhost`
- puerto: `5434`
- usuario: `postgres`
- password: `postgres`
- base: `postgres`

#### 2. Configurar el backend

1. Copia `backend/.env.example` a `backend/.env`.
2. Completa al menos estas variables:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/postgres
GEMINI_API_KEY=tu_api_key
```

3. Instala dependencias:

```powershell
cd backend
uv sync --dev
```

4. Arranca la API:

```powershell
uv run uvicorn shared.app:app --reload --host 0.0.0.0 --port 8000
```

La API queda disponible en `http://localhost:8000`.

#### 3. Levantar el frontend

En otra terminal:

```powershell
cd frontend
npm install
npm run dev
```

El frontend queda disponible segun la salida de Vite, normalmente en `http://localhost:5173/app/`.

La ruta funcional actual del profesor vive bajo `/app/teacher`, porque Vite y React Router usan `base` y `basename` en `/app/`.

### Opcion B: stack contenedorizado completo

Si quieres probar la API y PostgreSQL por Docker, el compose ya construye la imagen automaticamente desde el repo:

```powershell
docker compose up -d --build
```

Servicios esperados:

- PostgreSQL: `adam-edu-postgres`
- API: `adam-edu-api`

Puertos por defecto:

- PostgreSQL: `localhost:5434`
- API: `localhost:8123`

Notas:

- Para esta opcion, `GEMINI_API_KEY` debe existir en tu shell o en un archivo `.env` de la raiz usado por Docker Compose.
- Si solo necesitas base de datos para desarrollo, usa la Opcion A; es la ruta principal recomendada.

### Apagar el entorno Docker

```powershell
docker compose down
```

Si necesitas eliminar tambien el volumen local de PostgreSQL:

```powershell
docker compose down -v
```

## Variables de entorno

- `DATABASE_URL`: DSN principal de PostgreSQL para `shared.database`.
- `GEMINI_API_KEY`: requerido para authoring real, `/api/suggest` y tests `live_llm`.
- `CORS_ALLOWED_ORIGIN`: origen extra permitido en produccion.
- `STORYTELLER_MODEL`: override opcional del modelo usado por `/api/suggest`.

Base de ejemplo: [backend/.env.example](C:/Users/Juan%20Camilo%20Dorado/Downloads/ADAM-EDU/backend/.env.example)

## Validacion

- Backend tests:
  `uv run --directory backend pytest -q`
- Type checking:
  `uv run --directory backend mypy src`
- Frontend build:
  `npm --prefix frontend run build`
- Frontend tests:
  `npm --prefix frontend run test`
- Live LLM:
  `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

La suite default no debe tocar Gemini ni depender de side effects externos. Los tests `live_llm` quedan aislados detras de `RUN_LIVE_LLM_TESTS=1`.

## Nota historica

`docs/archive/MASTER_AUDIT_PLAN.md` se conserva solo como documento historico de auditoria y ya no define el alcance operativo del repo publicado.

## Para contributors

Lee [CLAUDE.md](C:/Users/Juan%20Camilo%20Dorado/Downloads/ADAM-EDU/CLAUDE.md) antes de abrir cambios grandes.

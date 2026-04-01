# CLAUDE.md

## Proyecto

ADAM EDU v8.0, en este repositorio, es un Teacher Authoring + Preview MVP. El alcance actual cubre el formulario docente, `/api/suggest`, la generacion del caso con LangGraph, el progreso SSE y el preview final del profesor.

## Mapa de dominios

- `backend/src/case_generator/`: dominio funcional del producto. Contiene la logica de negocio del authoring, el grafo LangGraph, prompts, schemas, adapters y servicios del generador de casos.
- `backend/src/shared/`: capa comun de app e infraestructura del MVP docente. Contiene la app FastAPI, base de datos, ORM, progress bus/SSE, sanitizacion y contratos de soporte usados por el flujo docente.
- `backend/tests/integration/`: validacion live del flujo docente y del grafo.
- `backend/tests/validation/`: validacion de shape, adapters y contratos auxiliares del frontend/output.
- `frontend/src/app/`: shell del frontend. Contiene router, entrypoint, layout base y estilos globales.
- `frontend/src/features/teacher-authoring/`: flujo docente real. Contiene formulario, submit del job, SSE y estados del authoring.
- `frontend/src/features/case-preview/`: preview editorial del caso generado y modulos `M1..M6`.
- `frontend/src/shared/`: API client, tipos compartidos, header, toast, utilidades y UI primitives transversales.

## Root files

- La raiz del repo debe permanecer minima y operativa.
- Mantener en root solo archivos que ayuden a correr, entender o empaquetar el MVP publicado.
- No dejar tooling personal, caches o documentos historicos en root si no estan documentados y usados por el equipo.
- `docker-compose.yml` existe para desarrollo local; no describe por si solo un despliegue productivo completo.
- `Makefile` es una conveniencia opcional, especialmente util en entornos Unix-like; no es el contrato principal del proyecto.
- La auditoria historica vive en `docs/archive/MASTER_AUDIT_PLAN.md`, no en la superficie operativa del repo.

## Reglas de importacion

- Usar imports absolutos por dominio: `from {dominio}.{modulo} import {simbolo}`.
- `shared/` no importa dominios de negocio. La unica excepcion es `shared/app.py` como composition root.
- Prohibido reintroducir `agent.*`, imports relativos complejos entre dominios o hacks con `sys.path`.
- Si una anotacion de tipo cruza dominios y puede crear ciclos, usar `from typing import TYPE_CHECKING` y referenciar el tipo como string o dentro del bloque `TYPE_CHECKING`.

## Convenciones de naming

- Codigo, modulos y simbolos en ingles.
- Terminos de dominio en espanol se preservan cuando son parte del lenguaje pedagogico o del prompt.
- Versiones de servicio deben alinearse con `backend/pyproject.toml` y exponerse de forma consistente.
- En `frontend/src/`, mantener la convencion top-level `app / features / shared`.
- No reabrir carpetas genericas como `components`, `pages`, `hooks`, `helpers`, `common` o `misc`.
- Los comentarios y docstrings deben describir el MVP actual, no sprints o fases historicas como si siguieran activos.

## Testing y validacion

- Suite default sin red: `uv run --directory backend pytest -q`
- Suite live Gemini: `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`
- Integracion live: `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest backend/tests/integration -q`
- Type checking: `uv run mypy backend/src/`
- Toda modificacion debe mantener intacto el flujo docente observable y cerrar con tests de authoring pasando.
- Los tests `live_llm` nunca deben ejecutarse por defecto en CI ni en el suite local base.

## Patrones prohibidos

- Queries ORM cross-dominio fuera de `shared/` o de los servicios propietarios del dominio.
- Imports directos de modelos desde lugares ajenos a `shared/`.
- Logica de negocio nueva dentro de migraciones, routers o prompts.
- Pragmas amplios para silenciar tipado sin una justificacion puntual.
- Hardcodear secretos, tokens, API keys o credenciales en codigo, prompts, fixtures o docs.

## Higiene estricta de prompts LLM

- Ningun prompt puede incluir API keys, bearer tokens, DSN, cookies, credenciales ni variables de entorno renderizadas.
- Todo contexto dinamico debe entrar por state/context injection controlado, nunca por concatenacion ciega de entradas del usuario a instrucciones de sistema.
- Si un valor controlado por usuario llega a un system prompt, debe tratarse como dato delimitado y no como instruccion confiable.
- Antes de cruzar una frontera LLM, usar `shared.sanitization.sanitize_untrusted_text()` o `sanitize_untrusted_payload()`.
- Cuando se use salida estructurada, preferir configuraciones resilientes y handlers de fallback para errores de validacion o respuestas vacias.

## Convenciones de migraciones

- Naming recomendado: `{hash}_{sprintN}_{descripcion}.py`
- Alembic debe seguir importando metadata desde `shared.models` y configuracion desde `shared.database`.

## Regla operativa principal

- `backend/src/case_generator/**` es la zona mas sensible del repo. No tocarla salvo que el cambio este directamente justificado por authoring y se valide extremo a extremo.
- `shared/` no debe crecer como cajon de sastre. Si aparece nueva logica de negocio, debe abrirse un dominio explicito nuevo en vez de meterla en `shared/`.
- `shared.models` y `shared.blueprint_schema` conservan legado retenido por continuidad de esquema y contratos internos. No eliminarlos ni expandirlos sin un plan separado de re-baseline.
- En esta fase existe un naming freeze: no renombrar `case_generator` ni `shared` sin abrir primero un refactor dedicado.
- En frontend tambien existe un naming freeze: no renombrar `app`, `teacher-authoring`, `case-preview` ni `shared` sin abrir primero un refactor dedicado.
- `studentProfile` y los modulos `M1..M6` se conservan porque forman parte del contrato actual de authoring/preview, aunque el repo publicado sea teacher-only.
- En esta fase no hacer comment cleanup dentro de `backend/src/case_generator/graph.py` ni `backend/src/case_generator/prompts.py` salvo necesidad funcional directa.
- No reintroducir runtime de estudiante, auth mock ni features experimentales en el flujo principal de este repo.
- Si aparece un nuevo frente de producto, abrir primero un plan separado antes de mezclarlo con el MVP docente.

# Security PR Checklist — ADAM-EDU

Obligatorio para PRs que toquen: `auth.py`, `app.py` (endpoints auth),
`internal_tasks.py`, `models.py` (modelos auth).

---

## Auth y tokens

- [ ] No se lee `actor_id`/`role`/`university_id` desde el body como fuente de verdad
- [ ] JWT verificado con JWKS (no con `SUPABASE_JWT_SECRET` en producción)
- [ ] `SUPABASE_SERVICE_ROLE_KEY` no aparece en responses, logs ni fixtures de test
- [ ] Token de invitación scrubbed antes de logs (usar `invite_hash_prefix`, no el token completo)

## Cloud Tasks

- [ ] Cloud Tasks OIDC validado (ya implementado en `shared/internal_tasks.py` — no reimplementar)

## Mensajes de error

- [ ] Mensajes 4xx no revelan: existencia de email, estado de invite (revocado vs inexistente), ni stack traces
- [ ] `detail` en responses usa códigos cortos sin información de diagnóstico interno

Mensajes de error auditados en Issue #46 (todos conformes):

| Endpoint | Códigos 4xx |
|---|---|
| `POST /api/auth/change-password` | `admin_role_required`, `password_rotation_not_required` |
| Rutas protegidas por actor compartido (`/api/admin/*`, `/api/teacher/*`, authoring teacher-only) | `invalid_token`, `profile_incomplete`, `membership_required`, `account_suspended`, `password_rotation_required`, `admin_role_required`, `teacher_role_required`, `admin_membership_context_required`, `teacher_membership_context_required` |
| `POST /api/invites/resolve` | `invalid_invite` |
| `POST /api/invites/redeem` | `membership_required`, `invalid_invite` |
| `POST /api/auth/activate/password` | `password_mismatch`, `invalid_invite`, `full_name_required` |
| `POST /api/auth/activate/oauth/complete` | `invalid_invite`, `invite_email_mismatch` |

Notas de precedencia auditada:

- `profile_incomplete` solo sale desde profile-state.
- `membership_required` solo sale desde membership-state.
- `password_rotation_required` se evalúa antes de errores de rol/contexto en rutas protegidas de negocio.
- `GET /api/auth/me` permanece fuera del guard compartido de `password_rotation_required` y del check de required profile fields para no romper bootstrap; si falta la fila `Profile`, sigue respondiendo `profile_incomplete`.
- `POST /api/auth/change-password` permanece fuera del guard compartido de `password_rotation_required` para no romper recuperación.

## Auditoría

- [ ] Nuevos flujos de auth cubiertos por `audit_log()` con `outcome` explícito
- [ ] Eventos de error (`outcome=denied`/`invalid`/`error`) incluyen `reason` descriptivo
- [ ] `GET /api/auth/me` emite `session.verified` (implementado en Issue #46)

## Rate limiting

- [ ] Rate limiting aplicado en nuevos endpoints de auth públicos
  - Si `max-instances > 1`: requiere Redis/Memorystore (ver TODO-005 en `TODOS.md`)
  - Si `max-instances = 1`: puede usar `slowapi` in-memory

## Tests

- [ ] Tests cubren el path de rechazo (401/403) además del happy path
- [ ] Si se agrega `audit_log()`: unit test que mockea `shared.app.audit_log` y verifica el call

---

## Referencias

- `backend/src/shared/auth.py` — `audit_log()`, `audit_event()`, `mask_email()`
- `backend/src/shared/internal_tasks.py` — OIDC Cloud Tasks (ya implementado)
- `docs/runbooks/cloud-run-deploy.md` — Rate Limiting Strategy
- `TODOS.md` — TODO-005 (rate limiting distribuido)

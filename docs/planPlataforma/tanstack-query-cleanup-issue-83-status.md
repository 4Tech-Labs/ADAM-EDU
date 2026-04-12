# Issue #83 — Cleanup post-TanStack Query

Estado real verificado en `main`:

- Los símbolos legacy que `#83` pedía eliminar del admin dashboard ya no existen en `frontend/src`.
- `AuthContext.tsx` todavía conserva guardrails activos de PKCE (`fetchActorOrThrow`, `actorQueryEnabled`, `actorRefreshTimeoutId` y el `setTimeout(0)` diferido). No son deuda técnica eliminable.
- El cierre correcto del issue es verificación final y documentación del estado, no simplificación agresiva del flujo auth ni poda de estado derivado del dashboard.

Verificaciones ejecutadas:

- `rg -n "reconcile|dashboardRequestIdRef|teacherOptionsRequestIdRef|isMountedRef|didLoadDashboard|RefreshMode|TeacherOptionsState|setIsRefreshing|setIsInitialLoading|setLastSyncedAt|setPageError|setRefreshError" frontend/src`
  Resultado: sin coincidencias.
- `rg -n "setInterval" frontend/src`
  Resultado: solo `frontend/src/features/teacher-authoring/AuthoringProgressTimeline.tsx`.
- `npm --prefix frontend run test`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`
- `uv run --directory backend pytest -q`

Conclusión:

- `#83` quedó absorbido casi por completo por `#72`, `#73`, `#78`, `#79` y `#82`.
- No se requieren cambios de código adicionales para considerar cerrado el cleanup ejecutable del frontend.

# TanStack Query — Plan de Adopción en ADAM-EDU

> **Objetivo**: auto-refresh silencioso, caché inteligente, datos siempre frescos sin parpadeos  
> y sin que el usuario salga y vuelva a la vista.  
> Base: TanStack Query v5 — patrones tomados de la documentación oficial (context7).

---

## Diagnóstico general

| Feature | Patrón actual | Problema |
|---------|---------------|---------|
| Admin Dashboard — summary + courses | `useState` + `useEffect` + listeners manuales de window focus + `requestIdRef` | El usuario debe salir y volver para ver datos actualizados; 29+ estados manuales; reconciliación manual |
| Admin Dashboard — teacher options | `useState` + `useEffect` de primer load | Nunca se invalida; dropdown stale si llega un invite nuevo |
| Admin Dashboard — mutations | `setSubmitting*` + `await refreshSummaryAndCourses()` manual | Refetch completo aunque solo cambie un campo |
| Teacher Authoring — sugerencias IA | `useState` flags manuales + `api.suggest()` directo | Sin deduplicación; doble clic lanza dos requests |
| Auth — actor profile | `useEffect` + `fetchActor` + flag de cancelación | Reconexiones de red no triggerizan re-fetch del perfil |
| Case Preview — módulos M1–M6 | Sin fetch (todo por props) | Sin problema — no requiere migración |
| Authoring SSE streaming | Custom hook con `AbortController` | Sin problema — TanStack no encaja en streams de larga duración |

**TanStack Query v5 NO está instalado.** No hay `QueryClientProvider` en el árbol de la app.

---

## Issue #0 — Setup Global

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: —

### Problema actual

No existe infraestructura centralizada de caché, deduplicación ni refetch automático.  
Cada componente reinventa esos mecanismos de forma manual.

### Solución

1. **Instalar dependencias**:
   ```
   npm install @tanstack/react-query@^5 @tanstack/react-query-devtools@^5
   ```

2. **Crear `frontend/src/lib/queryClient.ts`**:
   - `staleTime: 30_000` — datos frescos 30 s antes de background-refetch
   - `gcTime: 5 * 60_000` — mantener en caché 5 min sin observadores
   - `refetchOnWindowFocus: true` — refetch silencioso al volver a la pestaña
   - `refetchOnReconnect: true` — refetch al recuperar red
   - `retry: 1`

   ```ts
   import { QueryClient } from "@tanstack/react-query";

   export const queryClient = new QueryClient({
     defaultOptions: {
       queries: {
         staleTime: 30_000,
         gcTime: 5 * 60_000,
         refetchOnWindowFocus: true,
         refetchOnReconnect: true,
         retry: 1,
       },
     },
   });
   ```

3. **Crear `frontend/src/lib/queryKeys.ts`** — fábrica centralizada de query keys:

   ```ts
   import type { CourseFilters } from "@/features/admin-dashboard/adminDashboardModel";
   import type { IntentType, SuggestRequest } from "@/shared/api";

   export const queryKeys = {
     auth: {
       actor: () => ["auth", "actor"] as const,
     },
     admin: {
       summary:        () => ["admin", "summary"] as const,
       courses: (f: CourseFilters) => ["admin", "courses", f] as const,
       teacherOptions: () => ["admin", "teacher-options"] as const,
     },
     authoring: {
       suggest: (intent: IntentType, payload: SuggestRequest) =>
         ["authoring", "suggest", intent, payload] as const,
     },
   } as const;
   ```

4. **En `frontend/src/app/App.tsx`**: envolver la app con `<QueryClientProvider client={queryClient}>`.

5. Agregar `<ReactQueryDevtools initialIsOpen={false} />` en builds de desarrollo.

### Archivos a modificar

| Archivo | Acción |
|---------|--------|
| `frontend/package.json` | Agregar `@tanstack/react-query` y `@tanstack/react-query-devtools` |
| `frontend/src/app/App.tsx` | Agregar `QueryClientProvider` |
| `frontend/src/lib/queryClient.ts` | Crear (nuevo) |
| `frontend/src/lib/queryKeys.ts` | Crear (nuevo) |

### Criterio de aceptación

- [ ] `@tanstack/react-query` v5 instalado; TypeScript resuelve los tipos sin errores
- [ ] `QueryClientProvider` envuelve toda la app en `App.tsx`
- [ ] `staleTime: 30_000` y `refetchOnWindowFocus: true` como defaults globales
- [ ] React Query DevTools visible en el navegador en modo desarrollo
- [ ] `npm run build` pasa; funcionalidad existente sin regresiones

---

## Issue #1 — Teacher Authoring: Sugerencias de formulario

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: #0

### Problema actual

`frontend/src/features/teacher-authoring/AuthoringForm.tsx` gestiona las sugerencias de IA con
tres `useState` manuales: `isSuggestingScenario`, `isSuggestingTechniques`, `suggestError`.  
Sin deduplicación: dos clics rápidos lanzan dos peticiones idénticas al mismo endpoint.

**Endpoint**: `POST /api/suggest` (con `intent: "scenario"` | `"techniques"`)

### Solución

Reemplazar con dos `useMutation`:

```tsx
const scenarioMutation = useMutation({
  mutationFn: (payload: SuggestRequest) => api.suggest("scenario", payload),
  onSuccess: (data) => setScenarioDescription(data.scenario ?? ""),
});

const techniquesMutation = useMutation({
  mutationFn: (payload: SuggestRequest) => api.suggest("techniques", payload),
  onSuccess: (data) => {
    setSuggestedTechniques(data.techniques ?? []);
    setAreTechniquesStale(false);
  },
});
```

- Loading: `mutation.isPending` (eliminar `setIsSuggesting*`)
- Error: `mutation.error` (eliminar `suggestError`)

### Query keys

Mutations fire-and-forget — sin query keys de lectura, sin caché.

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/teacher-authoring/AuthoringForm.tsx` | Eliminar `isSuggestingScenario`, `isSuggestingTechniques`, `suggestError`; agregar dos `useMutation` |

### Criterio de aceptación

- [ ] Botones "Sugerir escenario" y "Sugerir técnicas" usan `useMutation`
- [ ] Loading derivado de `mutation.isPending` (no `useState` manual)
- [ ] Error derivado de `mutation.error` (no `suggestError`)
- [ ] Doble clic no lanza dos requests paralelas
- [ ] `npm run test` de la feature pasa

---

## Issue #2 — Admin Dashboard: Teacher Options

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: #0

### Problema actual

`frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` carga las opciones de docentes con:

- `teacherOptionsState` — objeto con 4 campos: `data`, `isInitialLoading`, `isRefreshing`, `error`
- `teacherOptionsRequestIdRef` — prevención manual de race conditions
- `didLoadTeacherOptionsRef` — detección first-load vs. background

La data **nunca se invalida** excepto en el error `stale_pending_teacher_invite`.  
Si un docente acepta un invite desde otra sesión, el dropdown del formulario no se actualiza.

**Endpoint**: `GET /api/admin/teacher-options`

### Solución

```tsx
const teacherOptionsQuery = useQuery({
  queryKey: queryKeys.admin.teacherOptions(),
  queryFn: () => api.admin.getTeacherOptions(),
  staleTime: 5 * 60_000,   // Docentes cambian poco; fresco 5 min
});
```

Invalidar tras mutaciones de invitación o al recibir error `stale_pending_teacher_invite`:

```ts
queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherOptions() });
```

### Query keys

- `["admin", "teacher-options"]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | Eliminar `teacherOptionsState`, `refreshTeacherOptions`, `teacherOptionsRequestIdRef`, `didLoadTeacherOptionsRef`; agregar `useQuery` |
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | Eliminar tipo `TeacherOptionsState` |

### Criterio de aceptación

- [ ] Opciones de docentes cargan en mount sin `useEffect` manual
- [ ] Objeto `teacherOptionsState` y toda su gestión manual eliminados
- [ ] Dropdown de asignación de docente funciona correctamente en modales de crear/editar
- [ ] `npm run test` pasa

---

## Issue #3 — Admin Dashboard: Summary & Courses (Migración Core)

**Complejidad**: Alta | **Riesgo**: Medio | **Depende de**: #0, #2

### Problema actual — causa raíz del reporte original

El usuario debe salir y volver a la vista para ver datos actualizados. El sistema actual:

- `refreshDashboard()` — función de 47 líneas con lógica dual initial/background
- `dashboardRequestIdRef` — prevención manual de race conditions
- `requestExternalRefresh()` con debounce manual de 750 ms
- `window.addEventListener("focus")` + `document.addEventListener("visibilitychange")`
- `reconcileDashboardSummary` y `reconcileCourseListResponse` — reconciliación manual ítem a ítem
- `Promise.all([getDashboardSummary(), listCourses()])` acoplados en una sola operación
- Summary y courses se re-renderizan **siempre juntos** aunque solo uno haya cambiado

**Endpoints**:
- `GET /api/admin/dashboard/summary`
- `GET /api/admin/courses?search=&semester=&status=&academic_level=&page=&page_size=`

### Solución

Dos `useQuery` **independientes** para máxima granularidad de re-renders:

```tsx
// Summary: auto-refresh cada 30 s, solo cuando la pestaña está visible
const summaryQuery = useQuery({
  queryKey: queryKeys.admin.summary(),
  queryFn: () => api.admin.getDashboardSummary(),
  staleTime: 30_000,
  refetchInterval: 30_000,
  refetchIntervalInBackground: false,  // no gastar requests si la pestaña está oculta
});

// Courses: reactivo a filtros; keepPreviousData evita parpadeo al cambiar filtros
const coursesQuery = useQuery({
  queryKey: queryKeys.admin.courses({
    search: deferredSearch,
    semester: semesterFilter,
    status: statusFilter,
    academicLevel: academicLevelFilter,
    page,
  }),
  queryFn: () => api.admin.listCourses(buildCourseFilters(page)),
  staleTime: 30_000,
  placeholderData: keepPreviousData,  // lista anterior visible mientras llega la nueva
});
```

### Tabla de reemplazos directos

| Código manual eliminado | Reemplazo TanStack |
|-------------------------|--------------------|
| `window.addEventListener("focus")` + debounce 750 ms | `refetchOnWindowFocus: true` (global desde Issue #0) |
| `dashboardRequestIdRef` | Deduplicación automática por `queryKey` |
| `reconcileDashboardSummary` | `structuralSharing: true` (default) — mismos datos = misma referencia, sin re-render |
| `reconcileCourseListResponse` ítem a ítem | `structuralSharing: true` |
| `isInitialLoading` + `isRefreshing` | `isLoading` (sin data + fetching) vs `isFetching` (background) |
| `isMountedRef` | Cleanup automático al desmontar el componente |
| `didLoadDashboardRef` | `isLoading` es `true` solo en el primer load sin data |
| `pageError` vs `refreshError` | `isError` para blocking; `isFetching && isError` para background |

### Query keys

- `["admin", "summary"]`
- `["admin", "courses", { search, semester, status, academicLevel, page }]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | **Eliminar**: `summary`, `coursesResponse`, `isInitialLoading`, `isRefreshing`, `pageError`, `refreshError`, `lastSyncedAt`, `isMountedRef`, `didLoadDashboardRef`, `dashboardRequestIdRef`, `lastExternalRefreshAtRef`, `refreshDashboard`, `applyDashboardSnapshot`, `requestExternalRefresh`, listeners de `focus`/`visibilitychange`. **Agregar**: dos `useQuery`. |
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | **Eliminar**: `reconcileDashboardSummary`, `reconcileCourseListResponse`, `areCourseItemsEqual`, tipo `RefreshMode` |

### Criterio de aceptación

- [ ] Contadores del resumen (cursos activos, docentes, estudiantes, ocupación) se actualizan cada 30 s **sin ninguna acción del usuario**
- [ ] Al volver a la pestaña los datos se revalidan automáticamente, sin salir de la vista
- [ ] Cambiar filtros (búsqueda, semestre, estado, página) no muestra pantalla en blanco — la lista anterior permanece visible hasta que llega la nueva (`keepPreviousData`)
- [ ] Tarjetas de resumen y tabla de cursos se actualizan **de forma independiente** — cambiar el nombre de un curso no re-renderiza las tarjetas de resumen
- [ ] Eliminados: `dashboardRequestIdRef`, `isMountedRef`, `didLoadDashboardRef`, listeners de window/document
- [ ] `AdminDashboardPage.tsx` reducido en al menos 200 líneas
- [ ] `npm run test` para admin-dashboard pasa

---

## Issue #4 — Admin Dashboard: Course Mutations

**Complejidad**: Media | **Riesgo**: Medio | **Depende de**: #3, #2

### Problema actual

Las 5 operaciones de escritura (crear curso, editar, archivar, invitar docente, regenerar enlace)
usan el mismo patrón manual:

1. `setSubmitting*(true)`
2. Llamada directa al API
3. `await refreshSummaryAndCourses()` — refetch completo post-mutación (aunque solo cambie uno)
4. `setCourseFormError()` en error
5. `setSubmitting*(false)` en `finally`

Resultado: tras cualquier mutación se refetchean summary + courses juntos aunque solo uno haya cambiado. Y si otro usuario hace un cambio, no se refleja aquí.

**Endpoints**:
- `POST /api/admin/courses`
- `PATCH /api/admin/courses/{courseId}`
- `POST /api/admin/teacher-invites`
- `POST /api/admin/courses/{courseId}/access-link/regenerate`

### Solución

Cada operación se convierte en `useMutation` con invalidación **granular** en `onSuccess`:

```tsx
const createCourseMutation = useMutation({
  mutationFn: (req: AdminCourseMutationRequest) => api.admin.createCourse(req),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.summary() });
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses({}) });
  },
  onError: (error) => {
    if (error instanceof ApiError && error.detail === "stale_pending_teacher_invite") {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherOptions() });
    }
  },
});

const regenerateLinkMutation = useMutation({
  mutationFn: (courseId: string) => api.admin.regenerateCourseAccessLink(courseId),
  onSuccess: () => {
    // Solo la lista de cursos cambia; el resumen NO
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses({}) });
  },
});
```

### Invalidación granular por operación

| Mutación | Invalida `summary` | Invalida `courses` | Invalida `teacher-options` |
|----------|:---:|:---:|:---:|
| Crear curso | ✅ | ✅ | — |
| Editar curso | — | ✅ | — |
| Archivar curso | ✅ | ✅ | — |
| Enviar invite docente | — | — | ✅ |
| Regenerar enlace de acceso | — | ✅ | — |

> **Nota sobre `transientAccessLinks`**: el estado transitorio que guarda links recién generados
> antes de que el servidor confirme se migra a actualización optimista con `queryClient.setQueryData`.

### Query keys invalidados

- `["admin", "summary"]`
- `["admin", "courses", ...]`
- `["admin", "teacher-options"]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | **Eliminar**: `submittingCreate`, `submittingEdit`, `submittingArchive`, `submittingInvite`, `regeneratingCourseId`, `transientAccessLinks`, `refreshSummaryAndCourses`, handlers `handleCreateCourse`, `handleEditCourse`, `handleArchiveCourse`, `handleInviteTeacher`, `handleRegenerateLink`. **Agregar**: 5 `useMutation`. |

### Criterio de aceptación

- [ ] Crear un curso actualiza inmediatamente la tabla y los contadores de resumen, sin reload
- [ ] Editar un curso actualiza solo la tabla (contadores no cambian a menos que cambie el estado)
- [ ] Archivar un curso decrementa el contador de cursos activos en tiempo real
- [ ] Enviar un invite refresca solo el dropdown de docentes en el modal
- [ ] Regenerar enlace actualiza solo esa fila de la tabla
- [ ] Los 5 estados `submitting*` manuales eliminados; loading desde `mutation.isPending`
- [ ] `npm run test` para admin-dashboard pasa

---

## Issue #5 — Auth: Actor Query

**Complejidad**: Media | **Riesgo**: Medio-Alto | **Depende de**: #0

### Problema actual

`frontend/src/app/auth/AuthContext.tsx` usa `useEffect` manual con:

1. Fetch de `/auth/me` en mount
2. Re-fetch en eventos `onAuthStateChange` de Supabase (SIGNED_IN, TOKEN_REFRESHED)
3. Flag de cancelación `cancelled` para evitar `setState` post-unmount
4. `window.setTimeout(() => fetchActor(), 0)` para diferir el fetch y evitar el deadlock del PKCE lock de Supabase

Las reconexiones de red **no** triggerizan re-fetch del perfil. El `setTimeout` es frágil y difícil de auditar.

**Endpoint**: `GET /auth/me`

### Solución

```tsx
const actorQuery = useQuery({
  queryKey: queryKeys.auth.actor(),
  queryFn: () => apiFetch("/auth/me").then((r) => r.json() as Promise<AuthMeActor>),
  enabled: !!session,           // Solo fetch si hay sesión activa
  staleTime: 5 * 60_000,        // Perfil fresco 5 min
  refetchOnWindowFocus: false,  // No refetch en cada cambio de pestaña
  refetchOnReconnect: true,     // Sí refetch al recuperar red
  retry: false,                 // No reintentar fallos de auth
});

// En onAuthStateChange:
// SIGNED_IN     → queryClient.invalidateQueries({ queryKey: queryKeys.auth.actor() })
// SIGNED_OUT    → queryClient.removeQueries({ queryKey: queryKeys.auth.actor() })
// TOKEN_REFRESHED → no acción (staleTime cubre este caso)
```

### Query keys

- `["auth", "actor"]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/app/auth/AuthContext.tsx` | Eliminar `fetchActor`, `actorRefreshTimeoutId`, flag `cancelled`; agregar `useQuery` + invalidación en `onAuthStateChange` |

### Criterio de aceptación

- [ ] Actor fetch ocurre al establecerse la sesión, sin hack de `setTimeout`
- [ ] Al hacer logout, `queryClient.removeQueries` limpia el caché del actor
- [ ] Al reconectar red, el perfil se revalida automáticamente
- [ ] Sin flag de cancelación manual
- [ ] Todas las rutas protegidas (admin, teacher) continúan funcionando
- [ ] `npm run test` pasa

---

## Issue #6 — Cleanup: Eliminar código obsoleto

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: Issues #1 al #5

### Código muerto a eliminar tras la migración

**`frontend/src/features/admin-dashboard/adminDashboardModel.ts`**:
- `reconcileDashboardSummary` — reemplazada por `structuralSharing` de TanStack
- `reconcileCourseListResponse` — ídem
- `areCourseItemsEqual` — ídem
- Tipo `RefreshMode` — el concepto initial/background ya no existe
- Tipo `TeacherOptionsState` — reemplazado por el estado de `useQuery`

**`frontend/src/features/admin-dashboard/AdminDashboardPage.tsx`**:
- Verificar que no queden refs manuales ni states de loading/error del sistema anterior
- Eliminar cualquier comentario `// TODO: migrate to TanStack` si los hubiera

**`frontend/src/app/auth/AuthContext.tsx`**:
- Verificar limpieza completa del patrón manual de fetch

**Auditoría de `setInterval`**: corroborar con grep que el único `setInterval` restante
en el frontend es el de la animación de puntos en `AuthoringProgressTimeline.tsx`.

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | Eliminar funciones de reconciliación y tipos obsoletos |
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | Verificación final de limpieza |
| `frontend/src/app/auth/AuthContext.tsx` | Verificación final de limpieza |

### Criterio de aceptación

- [ ] `grep -r "reconcile\|dashboardRequestIdRef\|teacherOptionsRequestIdRef\|isMountedRef\|didLoadDashboard\|RefreshMode\|TeacherOptionsState" frontend/src` retorna vacío
- [ ] `grep -r "setIsRefreshing\|setIsInitialLoading\|setLastSyncedAt\|setPageError\|setRefreshError" frontend/src` retorna vacío
- [ ] Único `setInterval` en el frontend es `AuthoringProgressTimeline.tsx` (animación)
- [ ] `npm run build && npm run test` pasa limpiamente
- [ ] `uv run --directory backend pytest -q` continúa verde (cero cambios en backend)

---

## Qué NO se migra (y por qué)

| Componente | Razón |
|-----------|-------|
| `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` | SSE de larga duración con `AbortController`. TanStack Query está diseñado para request/response, no para streams persistentes. El patrón actual es correcto y no causa problemas de UX. |
| `AuthoringProgressTimeline.tsx` — `setInterval` | Es animación de UI (puntos suspensivos `...`), no data fetching. |
| `CasePreview` y módulos M1–M6 | Reciben todos los datos vía props desde el componente padre; cero data fetching interno. |

---

## Grafo de dependencias

```
Issue #0 (Global Setup)
├── Issue #1 (Teacher Authoring: Suggestions)   ← aislado, riesgo bajo
├── Issue #2 (Admin: Teacher Options)            ← aislado, riesgo bajo
│       └── Issue #3 (Admin: Summary & Courses)  ← CORE — resolver antes que mutations
│               └── Issue #4 (Admin: Mutations)
└── Issue #5 (Auth: Actor Query)                 ← independiente, riesgo mayor

Issue #6 (Cleanup) ← depende de todos los anteriores
```

## Orden de ejecución recomendado

| # | Issue | Riesgo | Complejidad | Depende de |
|---|-------|--------|-------------|------------|
| 0 | Global Setup | Bajo | Bajo | — |
| 1 | Teacher Authoring: Suggestions | Bajo | Bajo | #0 |
| 2 | Admin: Teacher Options | Bajo | Bajo | #0 |
| 3 | Admin: Summary & Courses | Medio | **Alto** | #0, #2 |
| 4 | Admin: Course Mutations | Medio | Medio | #3, #2 |
| 5 | Auth: Actor Query | Medio-Alto | Medio | #0 |
| 6 | Cleanup | Bajo | Bajo | #1–#5 |

---

## Comandos de verificación

```bash
# Tras Issue #0 — build limpio
npm --prefix frontend run build

# Tras cada issue de features — test + lint
npm --prefix frontend run test
npm --prefix frontend run lint

# Tras Issue #6 — verificación final completa
npm --prefix frontend run build
npm --prefix frontend run test
uv run --directory backend pytest -q

# QA manual — Issue #3 (el fix principal)
# 1. Abrir /admin-dashboard, esperar 35 s
#    → contadores actualizan sin ninguna acción del usuario
# 2. Cambiar a otra pestaña por 30 s, volver
#    → datos se revalidan silenciosamente (sin parpadeo, sin spinner bloqueante)
# 3. Crear un curso desde el modal
#    → tabla y contadores actualizan inmediatamente, sin reload ni navigación

# QA manual — granularidad de re-renders
# 4. Editar el nombre de un curso
#    → solo esa fila cambia; tarjetas de resumen no parpadean
# 5. Regenerar enlace de acceso de un curso
#    → solo esa fila se actualiza; el resto del dashboard no se toca

# Verificar en React Query DevTools (dev mode)
# 6. Confirmar que ["admin", "summary"] y ["admin", "courses", {...}] tienen query keys distintos
# 7. Confirmar que summaryQuery tiene refetchInterval activo (30 s)
# 8. Confirmar que tras una mutación solo se invalidan los keys especificados en la tabla de arriba
```

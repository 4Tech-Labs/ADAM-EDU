# TanStack Query — Plan de Adopción en ADAM-EDU

> **Objetivo**: auto-refresh silencioso, caché inteligente, datos siempre frescos sin parpadeos  
> y sin que el usuario salga y vuelva a la vista.  
> Base: TanStack Query v5 — patrones verificados contra el codebase real y la documentación oficial.

---

## Errores detectados en el borrador anterior (registrados para referencia)

| # | Error | Severidad |
|---|-------|-----------|
| 1 | Directorio `lib/` no existe — la estructura es `app / features / shared` (CLAUDE.md). Los archivos van en `frontend/src/shared/`. | Alta |
| 2 | Import path incorrecto — `IntentType`/`SuggestRequest` están en `@/shared/adam-types`, NO en `@/shared/api`. | Alta |
| 3 | `CourseFilters` no existe en el codebase — `buildCourseFilters()` retorna un objeto inline sin tipo nombrado. Hay que definirlo en `queryKeys.ts`. | Media |
| 4 | `QueryClientProvider` en `App.tsx` — debe ir en `main.tsx`, FUERA de `AuthProvider`, porque Issue #6 necesita `useQueryClient()` dentro de `AuthProvider`. | Crítica |
| 5 | Cero infraestructura de testing — el plan decía "npm run test pasa" pero 18 tests existen sin `QueryClientProvider`. `AdminDashboardPage.test.tsx` rompería inmediatamente. | Crítica |
| 6 | Sin manejo global de 401 — `refetchInterval: 30_000` + token expirado = loop infinito de 401s cada 30 s. No había `queryCache.onError`. | Crítica |
| 7 | Sin `queryClient.clear()` en sign-out — sólo limpiaba `["auth", "actor"]`. Data de admin y authoring quedaba en caché. Data leak entre sesiones. | Alta |
| 8 | PKCE deadlock ignorado — reemplazaba `setTimeout(0)` con `invalidateQueries` directo en `onAuthStateChange`, que llama `getSession()` mientras el PKCE lock está activo. | Crítica |
| 9 | Optimistic update sin rollback — mencionaba `setQueryData` para `transientAccessLinks` pero no daba `onMutate`/`onError` con snapshot y rollback. | Media |
| 10 | Propiedad `logger` en QueryClient — fue eliminada en TanStack Query v5. No incluir en test utilities. | Media |

---

## Diagnóstico general

| Feature | Patrón actual | Problema |
|---------|---------------|---------|
| Admin Dashboard — summary + courses | `useState` + `useEffect` + listeners manuales de window focus + `requestIdRef` | El usuario debe salir y volver para ver datos actualizados; 33 useState; 6 useRef; reconciliación manual |
| Admin Dashboard — teacher options | `useState` + `useEffect` de primer load | Nunca se invalida; dropdown stale si llega un invite nuevo |
| Admin Dashboard — mutations | `setSubmitting*` + `await refreshSummaryAndCourses()` manual | Refetch completo aunque solo cambie un campo |
| Teacher Authoring — sugerencias IA | `useState` flags manuales + `api.suggest()` directo | Sin deduplicación; doble clic lanza dos requests |
| Auth — actor profile | `useEffect` + `fetchActor` + flag de cancelación + `setTimeout(0)` | Reconexiones de red no triggerizan re-fetch del perfil |
| Case Preview — módulos M1–M6 | Sin fetch (todo por props) | Sin problema — no requiere migración |
| Authoring SSE streaming | Custom hook con `AbortController` | Sin problema — TanStack no encaja en streams de larga duración |

**TanStack Query v5 NO está instalado.** No hay `QueryClientProvider` en el árbol de la app.

---

## Issue #0 — Setup Global (con manejo de 401 y limpieza en sign-out)

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: —

### Problema actual

No existe infraestructura centralizada de caché, deduplicación ni refetch automático. No hay manejo global de errores 401. No hay limpieza de caché al cerrar sesión. El proyecto usa `fetch` nativo (NO axios — no aplican interceptors de axios).

### Solución

**1. Instalar dependencias:**
```
npm install @tanstack/react-query@^5 @tanstack/react-query-devtools@^5
```

**2. Crear `frontend/src/shared/queryClient.ts`** (NO `lib/`):

```ts
import { QueryClient, QueryCache, MutationCache } from "@tanstack/react-query";
import { ApiError } from "@/shared/api";

function handleGlobalError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    // Token expirado. Supabase auto-refresh puede estar en vuelo.
    // NO llamar signOut() aquí (dependencia circular).
    // Cancelar y limpiar caché. Si el token está muerto,
    // onAuthStateChange(SIGNED_OUT) hará la limpieza final.
    queryClient.cancelQueries();
    queryClient.clear();
  }
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleGlobalError }),
  mutationCache: new MutationCache({ onError: handleGlobalError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        // Nunca reintentar 401/403 — son errores de auth, no transitorios
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          return false;
        }
        return failureCount < 1;
      },
    },
  },
});
```

> **Por qué esto resuelve el loop de 401**: `queryClient.clear()` detiene TODOS los `refetchInterval` activos. Supabase refresca el token y dispara `TOKEN_REFRESHED`, re-habilitando las queries. El `retry` custom evita martillar el servidor con reintentos de 401/403.

**3. Crear `frontend/src/shared/queryKeys.ts`:**

```ts
import type { IntentType, SuggestRequest } from "@/shared/adam-types"; // NO @/shared/api

export interface CourseFilters {
  search?: string;
  semester?: string;
  status?: string;
  academic_level?: string;
  page?: number;
  page_size?: number;
}

export const queryKeys = {
  auth: {
    actor: () => ["auth", "actor"] as const,
  },
  admin: {
    all:            () => ["admin"] as const,
    summary:        () => ["admin", "summary"] as const,
    courses:        (f?: CourseFilters) => ["admin", "courses", f] as const,
    teacherOptions: () => ["admin", "teacher-options"] as const,
  },
  authoring: {
    suggest: (intent: IntentType, payload: SuggestRequest) =>
      ["authoring", "suggest", intent, payload] as const,
  },
} as const;
```

Notas:
- `IntentType`/`SuggestRequest` importados de `@/shared/adam-types` (corrección de path respecto al borrador anterior).
- `CourseFilters` definido aquí porque no existe en el codebase.
- `admin.all()` agregado para invalidación masiva (útil en sign-out o error global).

**4. Modificar `frontend/src/app/main.tsx`** — `QueryClientProvider` FUERA de `AuthProvider`:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "@/shared/queryClient";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/app/">
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
        <ReactQueryDevtools initialIsOpen={false} />
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>
);
```

> **Crítico**: `QueryClientProvider` debe envolver a `AuthProvider` porque Issue #6 necesita `useQueryClient()` dentro de `AuthProvider`. Si se pone dentro de `App.tsx` (como decía el borrador anterior), el hook fallará en `AuthContext`.

### Archivos a modificar

| Archivo | Acción |
|---------|--------|
| `frontend/package.json` | Agregar `@tanstack/react-query` y `@tanstack/react-query-devtools` |
| `frontend/src/app/main.tsx` | Agregar `QueryClientProvider` envolviendo `AuthProvider` |
| `frontend/src/shared/queryClient.ts` | Crear (nuevo) |
| `frontend/src/shared/queryKeys.ts` | Crear (nuevo) |

### Criterio de aceptación

- [ ] `@tanstack/react-query` v5 instalado; TypeScript resuelve los tipos sin errores
- [ ] `QueryClientProvider` envuelve `AuthProvider` en `main.tsx` (NO en `App.tsx`)
- [ ] `queryCache.onError` + `mutationCache.onError` manejan 401 con `queryClient.clear()`
- [ ] `retry` custom no reintenta 401/403
- [ ] `staleTime: 30_000` y `refetchOnWindowFocus: true` como defaults globales
- [ ] React Query DevTools visible en modo desarrollo
- [ ] `npm run build` pasa; funcionalidad existente sin regresiones

---

## Issue #1 — Infraestructura de Testing

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: #0

### Problema actual

18 archivos de test existen. Ninguno envuelve componentes en `QueryClientProvider`. En cuanto cualquier componente use `useQuery`/`useMutation`, todos los tests que lo rendericen lanzarán:

```
No QueryClient set, use QueryClientProvider to set one
```

El archivo de setup actual (`frontend/src/test-setup.ts`) sólo importa `@testing-library/jest-dom`. No hay `createTestQueryClient()` ni `renderWithProviders()`.

### Solución

**Crear `frontend/src/shared/test-utils.tsx`:**

```tsx
import { type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,    // Tests no deben reintentar; fallos deben surfacear inmediatamente
        gcTime: 0,       // GC inmediato tras unmount para aislar tests entre sí
        staleTime: 0,    // Siempre stale en tests para control explícito
      },
      mutations: {
        retry: false,
      },
    },
    // NOTA: NO incluir `logger` — fue eliminado en TanStack Query v5
  });
}

interface WrapperOptions {
  queryClient?: QueryClient;
  initialEntries?: string[];
}

export function createWrapper(options: WrapperOptions = {}) {
  const qc = options.queryClient ?? createTestQueryClient();
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={options.initialEntries ?? ["/"]}>
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

export function renderWithProviders(
  ui: React.ReactElement,
  options: WrapperOptions & Omit<RenderOptions, "wrapper"> = {},
) {
  const { queryClient, initialEntries, ...renderOptions } = options;
  const testQC = queryClient ?? createTestQueryClient();
  return {
    ...render(ui, {
      wrapper: createWrapper({ queryClient: testQC, initialEntries }),
      ...renderOptions,
    }),
    queryClient: testQC,
  };
}
```

Decisiones de diseño:
- `retry: false` — fallos deben surfacear inmediatamente.
- `gcTime: 0` — garbage-collect tras unmount; las queries de un test no deben filtrarse al siguiente.
- Cada test recibe su propia instancia de `QueryClient` via `createTestQueryClient()` para aislamiento total.
- `createWrapper()` exportado por separado para `renderHook` en tests de hooks.
- **Sin `logger`** — fue removido en v5.

**Tests a actualizar progresivamente tras Issues #2–#6:**
- `AdminDashboardPage.test.tsx` — reemplazar `render(...)` con `renderWithProviders(...)`
- `AuthProvider.test.tsx` — envolver con `QueryClientProvider` tras Issue #6

### Archivos a modificar

| Archivo | Acción |
|---------|--------|
| `frontend/src/shared/test-utils.tsx` | Crear (nuevo) |
| Tests afectados | Actualizar en cada issue correspondiente |

### Criterio de aceptación

- [ ] `createTestQueryClient()` retorna client con `retry: false`, `gcTime: 0`, sin `logger`
- [ ] `renderWithProviders()` envuelve en `QueryClientProvider` + `MemoryRouter`
- [ ] Cada test recibe instancia aislada de `QueryClient`
- [ ] `createWrapper()` disponible para `renderHook`
- [ ] `npm run test` pasa después de cada issue subsecuente

---

## Issue #2 — Teacher Authoring: Sugerencias de formulario

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: #0

### Problema actual

`frontend/src/features/teacher-authoring/AuthoringForm.tsx` (líneas 51–53) gestiona sugerencias de IA con tres `useState` manuales: `isSuggestingScenario`, `isSuggestingTechniques`, `suggestError`. Sin deduplicación: doble clic lanza dos requests idénticos.

**Endpoint**: `POST /api/suggest` (con `intent: "scenario"` | `"techniques"`)

### Solución

Dos `useMutation`. Los efectos de UI (setear campos del form) van en el **call-site** de `mutate()`, no en las opciones del hook — esto es la práctica recomendada en v5 para efectos específicos de un componente.

```tsx
import { useMutation } from "@tanstack/react-query";

const scenarioMutation = useMutation({
  mutationFn: (payload: SuggestRequest) => api.suggest("scenario", payload),
});

const techniquesMutation = useMutation({
  mutationFn: (payload: SuggestRequest) => api.suggest("techniques", payload),
});

// Guard de doble-clic mediante isPending:
function handleSuggestScenario() {
  if (!canSuggest || scenarioMutation.isPending) return;
  scenarioMutation.mutate(buildSuggestPayload(), {
    onSuccess: (data) => {
      if (data.scenarioDescription) setScenarioDescription(data.scenarioDescription);
      if (data.guidingQuestion) setGuidingQuestion(data.guidingQuestion);
    },
  });
}

function handleSuggestTechniques() {
  if (!canSuggest || techniquesMutation.isPending) return;
  techniquesMutation.mutate(buildSuggestPayload(), {
    onSuccess: (data) => {
      if (data.suggestedTechniques.length > 0) {
        setSuggestedTechniques(data.suggestedTechniques);
        setAreTechniquesStale(false);
      }
    },
  });
}
```

### Estados eliminados

| Código manual | Reemplazo TanStack |
|---------------|-------------------|
| `isSuggestingScenario` (useState) | `scenarioMutation.isPending` |
| `isSuggestingTechniques` (useState) | `techniquesMutation.isPending` |
| `suggestError` (useState) | `scenarioMutation.error ?? techniquesMutation.error` |

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/teacher-authoring/AuthoringForm.tsx` | Eliminar 3 `useState`; agregar 2 `useMutation`; guard `isPending` contra doble clic |

### Criterio de aceptación

- [ ] Botones "Sugerir escenario" y "Sugerir técnicas" usan `useMutation`
- [ ] Loading derivado de `mutation.isPending` (no `useState` manual)
- [ ] Error derivado de `mutation.error` (no `suggestError`)
- [ ] Doble clic no lanza dos requests paralelas (guard `isPending`)
- [ ] `npm run test` pasa

---

## Issue #3 — Admin Dashboard: Teacher Options

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: #0, #1

### Problema actual

`AdminDashboardPage.tsx` (líneas 95–100, 127–131, 183–222) gestiona opciones de docentes con:

- `teacherOptionsState` — objeto con 4 campos: `data`, `isInitialLoading`, `isRefreshing`, `error`
- `teacherOptionsRequestIdRef` — prevención manual de race conditions
- `didLoadTeacherOptionsRef` — detección first-load vs. background
- `refreshTeacherOptions()` — ~40 líneas de lógica manual

La data **nunca se invalida** automáticamente. Si un docente acepta un invite desde otra sesión, el dropdown no se actualiza.

**Endpoint**: `GET /api/admin/teacher-options`

### Solución

```tsx
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/shared/queryKeys";

const teacherOptionsQuery = useQuery({
  queryKey: queryKeys.admin.teacherOptions(),
  queryFn: () => api.admin.getTeacherOptions(),
  staleTime: 5 * 60_000,   // Docentes cambian poco; fresco 5 min
});
```

Derivaciones de estado:
- `teacherOptionsQuery.data` → reemplaza `teacherOptionsState.data`
- `teacherOptionsQuery.isLoading` → reemplaza `teacherOptionsState.isInitialLoading`
- `teacherOptionsQuery.isFetching && !teacherOptionsQuery.isLoading` → reemplaza `isRefreshing`
- Error: `teacherOptionsQuery.error ? getAdminErrorMessage(...) : null`

Invalidar tras mutaciones de invitación o error `stale_pending_teacher_invite`:

```ts
queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherOptions() });
```

### Query keys

- `["admin", "teacher-options"]`

### Código eliminado

- `teacherOptionsState` (useState con 4 campos)
- `teacherOptionsRequestIdRef` (useRef)
- `didLoadTeacherOptionsRef` (useRef)
- `refreshTeacherOptions()` (useCallback, ~40 líneas)

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | Eliminar gestión manual; agregar `useQuery` |
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | Eliminar tipo `TeacherOptionsState` |

### Criterio de aceptación

- [ ] Opciones de docentes cargan en mount sin `useEffect` manual
- [ ] `teacherOptionsState` y toda su gestión eliminados
- [ ] Window focus revalida automáticamente (default global de Issue #0)
- [ ] Dropdown funciona correctamente en modales de crear/editar
- [ ] `npm run test` pasa (usando `renderWithProviders`)

---

## Issue #4 — Admin Dashboard: Summary & Courses (Migración Core)

**Complejidad**: Alta | **Riesgo**: Medio | **Depende de**: #0, #1, #3

### Problema actual — causa raíz del reporte original

El usuario debe salir y volver a la vista para ver datos actualizados. El sistema actual:

- `refreshDashboard()` — ~47 líneas con lógica dual initial/background
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
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { queryKeys, type CourseFilters } from "@/shared/queryKeys";

// Summary: auto-refresh cada 30 s, solo cuando la pestaña está visible
const summaryQuery = useQuery({
  queryKey: queryKeys.admin.summary(),
  queryFn: () => api.admin.getDashboardSummary(),
  staleTime: 30_000,
  refetchInterval: 30_000,
  refetchIntervalInBackground: false,  // no gastar requests si la pestaña está oculta
});

// Courses: reactivo a filtros; keepPreviousData evita parpadeo al cambiar filtros
const courseFilters: CourseFilters = {
  search: deferredSearch.trim() || undefined,
  semester: semesterFilter.trim() || undefined,
  status: statusFilter === "all" ? undefined : statusFilter,
  academic_level: academicLevelFilter === "all" ? undefined : academicLevelFilter,
  page,
  page_size: ADMIN_PAGE_SIZE,
};

const coursesQuery = useQuery({
  queryKey: queryKeys.admin.courses(courseFilters),
  queryFn: () => api.admin.listCourses(courseFilters),
  staleTime: 30_000,
  placeholderData: keepPreviousData,  // lista anterior visible mientras llega la nueva
  // keepPreviousData se importa como función de @tanstack/react-query en v5
});
```

> **Mitigación del loop de 401**: `refetchInterval: 30_000` es seguro porque Issue #0 configura `queryCache.onError` que llama `queryClient.clear()` ante un 401, deteniendo TODOS los intervals activos. Supabase refresca el token y dispara `TOKEN_REFRESHED`, re-habilitando las queries. El `retry` custom también skipea 401/403.

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

### Código eliminado (~150+ líneas)

**7 useState**: `summary`, `coursesResponse`, `isInitialLoading`, `isRefreshing`, `pageError`, `refreshError`, `lastSyncedAt`

**4 useRef**: `isMountedRef`, `didLoadDashboardRef`, `dashboardRequestIdRef`, `lastExternalRefreshAtRef`

**5 useCallback**: `refreshDashboard`, `applyDashboardSnapshot`, `requestExternalRefresh`, `refreshSummaryAndCourses`, `buildCourseFilters`

**2 useEffect**: fetch en mount + listeners focus/visibility

**4 funciones en model**: `reconcileDashboardSummary`, `reconcileCourseListResponse`, `areCourseItemsEqual`, `areTeacherAssignmentsEqual`

### Query keys

- `["admin", "summary"]`
- `["admin", "courses", { search, semester, status, academic_level, page, page_size }]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | **Eliminar**: 7 useState + 4 useRef + 5 useCallback + 2 useEffect de fetching/listeners. **Agregar**: 2 `useQuery`. |
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | **Eliminar**: `reconcileDashboardSummary`, `reconcileCourseListResponse`, `areCourseItemsEqual`, `areTeacherAssignmentsEqual` |
| `frontend/src/features/admin-dashboard/AdminDashboardPage.test.tsx` | Actualizar `renderPage()` a `renderWithProviders` |

### Criterio de aceptación

- [ ] Contadores del resumen se actualizan cada 30 s **sin ninguna acción del usuario**
- [ ] Al volver a la pestaña, los datos se revalidan automáticamente sin salir de la vista
- [ ] Cambiar filtros no muestra pantalla en blanco — la lista anterior permanece visible (`keepPreviousData`)
- [ ] Tarjetas de resumen y tabla de cursos se actualizan **de forma independiente**
- [ ] Eliminados: `dashboardRequestIdRef`, `isMountedRef`, `didLoadDashboardRef`, listeners de window/document
- [ ] `AdminDashboardPage.tsx` reducido en al menos 150 líneas
- [ ] `npm run test` pasa

---

## Issue #5 — Admin Dashboard: Course Mutations (con optimistic updates y rollback)

**Complejidad**: Media | **Riesgo**: Medio | **Depende de**: #3, #4

### Problema actual

Las 5 operaciones de escritura usan el mismo patrón manual:

1. `setSubmitting*(true)`
2. Llamada directa al API
3. `await refreshSummaryAndCourses()` — refetch completo post-mutación
4. `setCourseFormError()` en error
5. `setSubmitting*(false)` en `finally`

`transientAccessLinks` (`Record<string, string>`) guarda links recién generados sin mecanismo de rollback.

**Endpoints**:
- `POST /api/admin/courses`
- `PATCH /api/admin/courses/{courseId}`
- `POST /api/admin/teacher-invites`
- `POST /api/admin/courses/{courseId}/access-link/regenerate`

### Solución

5 `useMutation` con invalidación granular. `onSuccess` en las opciones del hook para invalidación de caché (intrínseco a la mutación). Efectos de UI (cerrar modal, toast) en el **call-site** de `mutate()`.

**Create Course:**

```tsx
const createCourseMutation = useMutation({
  mutationFn: (req: AdminCourseMutationRequest) => api.admin.createCourse(req),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.summary() });
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses() });
  },
  onError: (error) => {
    if (error instanceof ApiError && error.detail === "stale_pending_teacher_invite") {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherOptions() });
    }
  },
});

// Call-site (efectos de UI van aquí):
createCourseMutation.mutate(buildCoursePayload(createForm), {
  onSuccess: (createdItem) => {
    if (createdItem.access_link) {
      setTransientAccessLinks(prev => ({ ...prev, [createdItem.id]: createdItem.access_link! }));
    }
    setIsCreateOpen(false);
    setPage(1);
    showToast("Curso creado correctamente.", "success");
  },
  onError: (error) => {
    setCourseFormError(getAdminErrorMessage(error, "No se pudo crear el curso."));
  },
});
```

**Regenerate Link — optimistic update completo con rollback:**

```tsx
const regenerateLinkMutation = useMutation({
  mutationFn: (courseId: string) => api.admin.regenerateCourseAccessLink(courseId),
  onMutate: async (_courseId) => {
    // 1. Cancelar refetches activos para que no sobreescriban el update optimista
    await queryClient.cancelQueries({ queryKey: queryKeys.admin.courses() });
    // 2. Snapshot para rollback en caso de error
    const previousTransientLinks = { ...transientAccessLinks };
    return { previousTransientLinks };
  },
  onSuccess: (data) => {
    // 3. Aplicar link real del servidor
    setTransientAccessLinks(prev => ({ ...prev, [data.course_id]: data.access_link }));
    showToast("Enlace regenerado correctamente.", "success");
  },
  onError: (_error, _courseId, context) => {
    // 4. Rollback al snapshot
    if (context?.previousTransientLinks) {
      setTransientAccessLinks(context.previousTransientLinks);
    }
    const message = getAdminErrorMessage(_error, "No se pudo regenerar el enlace.");
    setCourseFormError(message);
    showToast(message, "error");
  },
  onSettled: () => {
    // 5. SIEMPRE re-fetch para que el servidor sea la fuente de verdad
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses() });
  },
});
```

> `transientAccessLinks` se **mantiene como `useState`** — es datos efímeros de UI, no datos del servidor. `buildLinkPresentation()` ya los combina con los datos del servidor.

**Invite Teacher — optimistic update del dropdown:**

```tsx
const inviteTeacherMutation = useMutation({
  mutationFn: (req: { full_name: string; email: string }) =>
    api.admin.createTeacherInvite(req),
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherOptions() });
  },
});

// Call-site (actualización optimista del dropdown y UI):
inviteTeacherMutation.mutate(
  { full_name: inviteName.trim(), email: inviteEmail.trim() },
  {
    onSuccess: (createdInvite) => {
      // Actualizar caché de teacher-options optimistamente
      queryClient.setQueryData(
        queryKeys.admin.teacherOptions(),
        (old: AdminTeacherOptionsResponse | undefined) => {
          if (!old) return old;
          return {
            active_teachers: old.active_teachers,
            pending_invites: sortPendingInvites([
              ...old.pending_invites,
              teacherInviteToPendingOption(createdInvite),
            ]),
          };
        },
      );
      // Seleccionar el invite en el form correspondiente
      const encodedValue = encodeTeacherOptionValue({
        kind: "pending_invite",
        invite_id: createdInvite.invite_id,
      });
      if (inviteTarget === "create") {
        setCreateForm(prev => ({ ...prev, teacher_option_value: encodedValue }));
      } else {
        setEditForm(prev => ({ ...prev, teacher_option_value: encodedValue }));
      }
      setInviteSuccess({ email: createdInvite.email, activationLink: createdInvite.activation_link });
      showToast(`Invitación enviada a ${createdInvite.email}.`, "success");
    },
    onError: (error) => {
      setInviteFormError(getAdminErrorMessage(error, "No se pudo enviar la invitación."));
    },
  },
);
```

### Invalidación granular por operación

| Mutación | Invalida `summary` | Invalida `courses` | Invalida `teacher-options` |
|----------|:---:|:---:|:---:|
| Crear curso | ✅ | ✅ | — |
| Editar curso | — | ✅ | — |
| Archivar curso | ✅ | ✅ | — |
| Enviar invite docente | — | — | ✅ |
| Regenerar enlace de acceso | — | ✅ | — |

### Estados eliminados

| Antes | Después |
|-------|---------|
| `submittingCreate` (useState) | `createCourseMutation.isPending` |
| `submittingEdit` (useState) | `editCourseMutation.isPending` |
| `submittingArchive` (useState) | `archiveCourseMutation.isPending` |
| `submittingInvite` (useState) | `inviteTeacherMutation.isPending` |
| `regeneratingCourseId` (useState) | `regenerateLinkMutation.variables` (el courseId pasado) |

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | **Eliminar**: 5 `submitting*` + `regeneratingCourseId` + handlers manuales. **Agregar**: 5 `useMutation`. |

### Criterio de aceptación

- [ ] Crear un curso actualiza inmediatamente la tabla y los contadores, sin reload
- [ ] Editar un curso actualiza solo la tabla (contadores no cambian salvo si cambia el estado)
- [ ] Archivar decrementa el contador de cursos activos en tiempo real
- [ ] Invite refresca solo el dropdown de docentes en el modal
- [ ] Regenerar link muestra el nuevo link; rollback completo si falla (`onMutate` snapshot + `onError` restore)
- [ ] 5 estados `submitting*` y `regeneratingCourseId` eliminados; loading desde `mutation.isPending`
- [ ] `npm run test` pasa

---

## Issue #6 — Auth: Actor Query (con protección PKCE)

**Complejidad**: Media | **Riesgo**: Medio-Alto | **Depende de**: #0, #1

### Problema actual

`frontend/src/app/auth/AuthContext.tsx` usa `useEffect` manual con:

1. Fetch de `/auth/me` en mount
2. Re-fetch en eventos `onAuthStateChange` de Supabase (`SIGNED_IN`, `TOKEN_REFRESHED`)
3. Flag de cancelación `cancelled` para evitar `setState` post-unmount
4. `window.setTimeout(() => fetchActor(), 0)` para diferir el fetch y evitar el deadlock del PKCE lock de Supabase

Las reconexiones de red **no** triggerizan re-fetch del perfil. Sin embargo, el `setTimeout(0)` existe por una razón técnica válida que **no se debe eliminar**.

**Endpoint**: `GET /auth/me`

### Solución

**Preservar el `setTimeout(0)` para SIGNED_IN** (el PKCE lock se libera al siguiente macrotask). Delegar el fetch a `useQuery`.

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/shared/queryKeys";

// Dentro de AuthProvider:
const queryClient = useQueryClient();

const actorQuery = useQuery({
  queryKey: queryKeys.auth.actor(),
  queryFn: async () => {
    const res = await apiFetch("/auth/me");
    return (await res.json()) as AuthMeActor;
  },
  enabled: !!session,           // Solo fetch si hay sesión activa
  staleTime: 5 * 60_000,        // Perfil fresco 5 min
  refetchOnWindowFocus: false,  // No refetch en cada cambio de pestaña
  refetchOnReconnect: true,     // Sí refetch al recuperar red ← resuelve el problema original
  retry: false,                 // No reintentar fallos de auth
});

const actor = actorQuery.data ?? null;
```

**En `onAuthStateChange`:**

```tsx
const { data: listenerData } = supabase.auth.onAuthStateChange(
  (event, nextSession) => {
    if (cancelled) return;

    if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED" || event === "INITIAL_SESSION") {
      setSession(nextSession);
      if (nextSession && event === "SIGNED_IN") {
        // CRÍTICO: Defer la invalidación al siguiente macrotask.
        // El PKCE lock se mantiene durante el callback de onAuthStateChange.
        // Si invalidateQueries se llama aquí directamente, queryFn se ejecuta
        // inmediatamente → apiFetch → getBearerToken → getSession() → DEADLOCK.
        deferredInvalidationId = window.setTimeout(() => {
          if (!cancelled) {
            queryClient.invalidateQueries({ queryKey: queryKeys.auth.actor() });
          }
        }, 0);
      }
      // TOKEN_REFRESHED: NO invalidar — el perfil no cambió.
      // staleTime: 5 min cubre el eventual refetch.
    } else if (event === "SIGNED_OUT") {
      setSession(null);
      setError(null);
      // Limpiar TODOS los datos cacheados para prevenir data leak entre sesiones
      queryClient.clear();
    }
  },
);
```

**En `signOut()`:**

```tsx
const signOut = useCallback(async () => {
  const supabase = getSupabaseClient();
  if (supabase) await supabase.auth.signOut();
  setSession(null);
  setError(null);
  // queryClient.clear() también se llama en el handler SIGNED_OUT,
  // pero se llama aquí también para el path síncrono de signOut
  queryClient.clear();
}, [queryClient]);
```

**`refreshActor` en el context value:**

```tsx
refreshActor: async () => {
  await queryClient.invalidateQueries({ queryKey: queryKeys.auth.actor() });
},
```

### Decisiones de diseño

| Decisión | Razón |
|----------|-------|
| `setTimeout(0)` preservado solo para `SIGNED_IN` | PKCE lock se libera al siguiente macrotask |
| `TOKEN_REFRESHED` no invalida | El perfil no cambió; `staleTime` maneja el refetch eventual |
| `queryClient.clear()` en `SIGNED_OUT` | Purga TODO (auth, admin, authoring); previene data leak entre sesiones |
| `enabled: !!session` | No hacer fetch sin sesión activa |
| `refetchOnWindowFocus: false` | El perfil no cambia frecuentemente; evitar requests innecesarios |
| `refetchOnReconnect: true` | Al recuperar red, verificar que el perfil siga activo |

### Query keys

- `["auth", "actor"]`

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/app/auth/AuthContext.tsx` | Eliminar `fetchActor` useCallback + flag `cancelled`; agregar `useQuery`; preservar `setTimeout(0)` para SIGNED_IN; agregar `queryClient.clear()` en sign-out |
| `frontend/src/app/auth/AuthProvider.test.tsx` | Envolver con `QueryClientProvider` wrapper |

### Criterio de aceptación

- [ ] Actor fetch ocurre al establecerse la sesión (`enabled: !!session`), sin hack de fetch manual
- [ ] `setTimeout(0)` preservado para `SIGNED_IN` — PKCE safety
- [ ] `TOKEN_REFRESHED` NO triggerizan invalidación inmediata
- [ ] `SIGNED_OUT` llama `queryClient.clear()` para TODA la data cacheada
- [ ] `signOut()` también llama `queryClient.clear()`
- [ ] Al reconectar red, el perfil se revalida automáticamente (`refetchOnReconnect: true`)
- [ ] `refreshActor()` usa `invalidateQueries` en lugar de llamada directa
- [ ] Sin flag de cancelación manual (`cancelled`)
- [ ] Todas las rutas protegidas (admin, teacher) continúan funcionando
- [ ] `npm run test` pasa

---

## Issue #7 — Cleanup: Eliminar código obsoleto

**Complejidad**: Baja | **Riesgo**: Bajo | **Depende de**: Issues #2 al #6

### Código muerto a eliminar tras la migración

**`frontend/src/features/admin-dashboard/adminDashboardModel.ts`**:
- `reconcileDashboardSummary` — reemplazada por `structuralSharing` de TanStack
- `reconcileCourseListResponse` — ídem
- `areCourseItemsEqual` — ídem
- `areTeacherAssignmentsEqual` — ídem
- Tipo `TeacherOptionsState` — reemplazado por el estado de `useQuery`

**`frontend/src/features/admin-dashboard/AdminDashboardPage.tsx`**:
- Tipo `RefreshMode = "initial" | "background"` (línea 82) — el concepto ya no existe
- Verificar que no queden refs manuales ni states de loading/error del sistema anterior

**`frontend/src/app/auth/AuthContext.tsx`**:
- Verificar limpieza completa: sin `fetchActor`, sin `actorRefreshTimeoutId` sin limpiar, sin flag `cancelled` suelto

### Auditoría con grep

```bash
# Debe retornar vacío:
grep -rn "reconcile\|dashboardRequestIdRef\|teacherOptionsRequestIdRef\|isMountedRef\|didLoadDashboard\|RefreshMode\|TeacherOptionsState\|setIsRefreshing\|setIsInitialLoading\|setLastSyncedAt\|setPageError\|setRefreshError" frontend/src

# Solo debe aparecer en AuthoringProgressTimeline.tsx:
grep -rn "setInterval" frontend/src
```

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | Eliminar funciones de reconciliación y tipos obsoletos |
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | Verificación final + eliminar `RefreshMode` |
| `frontend/src/app/auth/AuthContext.tsx` | Verificación final de limpieza |

### Criterio de aceptación

- [ ] `grep` de símbolos eliminados retorna vacío
- [ ] Único `setInterval` en el frontend es `AuthoringProgressTimeline.tsx` (animación)
- [ ] `npm run build && npm run test && npm run lint` pasa limpiamente
- [ ] `uv run --directory backend pytest -q` continúa verde (cero cambios en backend)

---

## Qué NO se migra (y por qué)

| Componente | Razón |
|-----------|-------|
| `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` | SSE de larga duración con `AbortController`. TanStack Query está diseñado para request/response, no para streams persistentes. |
| `AuthoringProgressTimeline.tsx` — `setInterval` | Es animación de UI (puntos suspensivos `...`), no data fetching. |
| `CasePreview` y módulos M1–M6 | Reciben todos los datos vía props desde el componente padre; cero data fetching interno. |
| `apiFetch()` y `api.*` | Son la capa de transporte. `queryFn` delega a ellas. No se reemplazan. |
| `getAdminErrorMessage()` | Sigue siendo necesaria para mapear errores de API a mensajes en español. |
| `buildLinkPresentation()` | Sigue siendo necesaria; `transientAccessLinks` permanece como estado local de UI. |

---

## Grafo de dependencias

```
Issue #0 (Global Setup: queryClient, queryKeys, QueryClientProvider en main.tsx)
├── Issue #1 (Testing: test-utils.tsx)                    ← bajo riesgo, ejecutar pronto
├── Issue #2 (Teacher Authoring: Suggestions)             ← aislado, bajo riesgo
├── Issue #3 (Admin: Teacher Options)                     ← bajo riesgo
│       └── Issue #4 (Admin: Summary & Courses)           ← CORE — antes que mutations
│               └── Issue #5 (Admin: Mutations)
└── Issue #6 (Auth: Actor Query)                          ← independiente, MAYOR RIESGO

Issue #7 (Cleanup) ← depende de todos los anteriores
```

## Orden de ejecución recomendado

| # | Issue | Riesgo | Complejidad | Depende de |
|---|-------|--------|-------------|------------|
| 0 | Global Setup | Bajo | Bajo | — |
| 1 | Testing Infrastructure | Bajo | Bajo | #0 |
| 2 | Teacher Authoring: Suggestions | Bajo | Bajo | #0 |
| 3 | Admin: Teacher Options | Bajo | Bajo | #0, #1 |
| 4 | Admin: Summary & Courses | Medio | **Alto** | #0, #1, #3 |
| 5 | Admin: Course Mutations | Medio | Medio | #4, #3 |
| 6 | Auth: Actor Query | **Medio-Alto** | Medio | #0, #1 |
| 7 | Cleanup | Bajo | Bajo | #2–#6 |

> Issue #6 (Auth) es el de mayor riesgo por tocar la ruta de autenticación con el constraint PKCE. Ejecutar después de ganar confianza con la migración del admin dashboard.

---

## Archivos críticos (referencia rápida)

| Archivo | Issues que lo modifican |
|---------|------------------------|
| `frontend/src/app/main.tsx` | #0 |
| `frontend/src/shared/queryClient.ts` | #0 (nuevo) |
| `frontend/src/shared/queryKeys.ts` | #0 (nuevo) |
| `frontend/src/shared/test-utils.tsx` | #1 (nuevo) |
| `frontend/src/features/teacher-authoring/AuthoringForm.tsx` | #2 |
| `frontend/src/features/admin-dashboard/AdminDashboardPage.tsx` | #3, #4, #5, #7 |
| `frontend/src/features/admin-dashboard/adminDashboardModel.ts` | #3, #4, #7 |
| `frontend/src/features/admin-dashboard/AdminDashboardPage.test.tsx` | #1, #4 |
| `frontend/src/app/auth/AuthContext.tsx` | #6, #7 |
| `frontend/src/app/auth/AuthProvider.test.tsx` | #1, #6 |
| `frontend/src/shared/adam-types.ts` | referencia — `IntentType`, `SuggestRequest`, tipos de admin |
| `frontend/src/shared/api.ts` | referencia — `ApiError`, `apiFetch`, `api.*` endpoints |

---

## Comandos de verificación

```bash
# Tras Issue #0 — build limpio
npm --prefix frontend run build

# Tras cada issue de features — test + lint
npm --prefix frontend run test
npm --prefix frontend run lint

# Tras Issue #7 — verificación final completa
npm --prefix frontend run build
npm --prefix frontend run test
npm --prefix frontend run lint
uv run --directory backend pytest -q

# QA manual — Issue #4 (el fix principal)
# 1. Abrir /admin/dashboard, esperar 35 s
#    → contadores actualizan sin ninguna acción del usuario
# 2. Cambiar a otra pestaña por 30 s, volver
#    → datos se revalidan silenciosamente (sin parpadeo, sin spinner bloqueante)
# 3. Crear un curso desde el modal
#    → tabla y contadores actualizan inmediatamente, sin reload ni navegación

# QA manual — granularidad de re-renders
# 4. Editar el nombre de un curso
#    → solo esa fila cambia; tarjetas de resumen no parpadean
# 5. Regenerar enlace de acceso de un curso
#    → solo esa fila se actualiza; el resto del dashboard no se toca
# 6. Simular error en regenerar enlace (desconectar red)
#    → el link anterior debe reaparecer (rollback del optimistic update)

# QA manual — manejo de 401 (Issue #0)
# 7. Dejar el dashboard abierto, invalidar el token en Supabase Studio
#    → NO debe haber loop de 401s cada 30 s
#    → Supabase debe refrescar el token y restaurar las queries automáticamente

# Verificar en React Query DevTools (dev mode)
# 8. Confirmar que ["admin", "summary"] y ["admin", "courses", {...}] tienen query keys distintos
# 9. Confirmar que summaryQuery tiene refetchInterval activo (30 s)
# 10. Confirmar que tras una mutación solo se invalidan los keys de la tabla de arriba
# 11. Confirmar que al hacer sign-out, TODAS las queries desaparecen del cache
```

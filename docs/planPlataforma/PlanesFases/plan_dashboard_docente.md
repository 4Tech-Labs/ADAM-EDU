# Portal Docente — Dashboard: Plan de Implementación por Issues

> **Mockup de referencia (OBLIGATORIO):** `docs/planPlataforma/Mockups/profesor/Dashboard_Portal_Profesor.html`
> El frontend debe ser una réplica pixel-perfect de ese mockup. Toda decisión de diseño parte de ese archivo.

---

## Contexto

El docente actualmente aterriza en el `AuthoringForm` al hacer login. Este plan introduce el **Portal Docente** como nueva landing page post-autenticación. El dashboard consolida: cursos asignados al docente, casos activos con deadline vigente, y accesos rápidos a las acciones clave.

### Decisiones de arquitectura aprobadas

| Decisión | Valor |
|---|---|
| Landing post-login del docente | `/teacher/dashboard` |
| SiteHeader global | Suprimido en `/teacher/dashboard` (dashboard tiene su propio header) |
| Endpoint de casos | `GET /api/teacher/cases` (separado de cursos) |
| Paginación de casos | Client-side (todos los datos en un fetch, `slice()` en frontend) |
| Promedio en course cards | `"—"` placeholder (sin sistema de calificaciones en V1) |

---

## Mapa de Arquitectura

```
ROUTING (App.tsx)
─────────────────────────────────────────────────
/teacher/login          → TeacherLoginPage
/teacher/activate       → TeacherActivatePage
/teacher/dashboard      → TeacherDashboardPage  ← NEW (antes del catch-all)
/teacher/*              → TeacherAuthoringPage  (existente, sin tocar)

RootRedirect: teacher → /teacher/dashboard  ← ACTUALIZAR

SiteHeader suprimido para:
  /admin/dashboard   (existente)
  /teacher/dashboard (NUEVO — mismo patrón)

─────────────────────────────────────────────────
FLUJO DE DATOS
─────────────────────────────────────────────────

Browser → GET /api/teacher/courses
  └─ require_teacher_actor (JWT)
  └─ Membership(user_id=actor.auth_user_id, role='teacher', status='active')
  └─ Course(teacher_membership_id=membership.id)
  └─ CourseMembership COUNT por curso
  └─ TeacherCoursesResponse[]

Browser → GET /api/teacher/cases
  └─ require_teacher_actor (JWT)
  └─ ensure_legacy_teacher_bridge → User.id
  └─ Assignment(teacher_id=user.id, deadline >= now())
  └─ ORDER BY deadline ASC
  └─ TeacherCasesResponse[]

─────────────────────────────────────────────────
ÁRBOL DE COMPONENTES REACT
─────────────────────────────────────────────────

TeacherDashboardPage
├── DashboardHeader          (actor.profile.full_name → initials + nombre)
├── QuickActionsSection      (3 gradient cards)
│   ├── Card "Crear Nuevo Caso"    → navigate('/teacher')
│   ├── Card "Gestión de Casos"    → scrollIntoView('#cases-section')
│   └── Card "Reportes Globales"   → showToast("Próximamente")
├── CursosActivosSection     (useTeacherCourses hook)
│   ├── SearchInput          (filtro client-side por course.title)
│   └── CourseCard[]         (status-aware: active/inactive)
└── CasosActivosSection      (useTeacherCases hook)  id="cases-section"
    ├── TableHeader          (+ botón "Crear nuevo caso")
    ├── CasoRow[]            (Ver Caso | Entregas | Editar — placeholders V1)
    └── TablePagination      (client-side, PAGE_SIZE=10)

─────────────────────────────────────────────────
ARCHIVOS CREADOS / MODIFICADOS
─────────────────────────────────────────────────

NUEVOS (backend):
  backend/src/shared/teacher_router.py
  backend/src/shared/teacher_reads.py

NUEVOS (frontend):
  frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx
  frontend/src/features/teacher-dashboard/DashboardHeader.tsx
  frontend/src/features/teacher-dashboard/QuickActionsSection.tsx
  frontend/src/features/teacher-dashboard/CursosActivosSection.tsx
  frontend/src/features/teacher-dashboard/CasosActivosSection.tsx
  frontend/src/features/teacher-dashboard/useTeacherDashboard.ts

MODIFICADOS:
  backend/src/shared/app.py              (registrar teacher_router)
  backend/alembic/versions/XXXX_add_deadline_to_assignments.py  (NUEVA migración)
  frontend/src/app/App.tsx               (agregar ruta + lógica SiteHeader)
  frontend/src/app/auth/RootRedirect.tsx (teacher → /teacher/dashboard)
  frontend/src/shared/queryKeys.ts       (agregar namespace teacher)
  frontend/src/shared/api.ts             (agregar api.teacher.*)
```

---

## Orden de ejecución

```
Fase 1 — Paralelo (sin dependencias):
  Issue 1 → Backend: teacher_router + /courses
  Issue 3 → Frontend: routing + scaffolding

Fase 2 — Secuencial (requieren Fase 1):
  Issue 2 → Backend: migración deadline + /cases  (requiere Issue 1)
  Issue 4 → Frontend: TanStack Query hooks        (requiere Issue 3)

Fase 3 — Paralelo (requieren Issues 3 y 4):
  Issue 5 → DashboardHeader
  Issue 6 → QuickActionsSection
  Issue 7 → CursosActivosSection
  Issue 8 → CasosActivosSection
```

---

## Issue 1 — [Backend] Teacher Router + `GET /api/teacher/courses`

### Resumen
Crear el router FastAPI del docente y el primer endpoint que devuelve los cursos asignados al docente autenticado, con conteo de estudiantes y casos activos por curso.

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `backend/src/shared/teacher_router.py` |
| CREAR | `backend/src/shared/teacher_reads.py` |
| MODIFICAR | `backend/src/shared/app.py` |

### `teacher_reads.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from .models import Course, CourseMembership, Membership
from .auth import CurrentActor


@dataclass
class TeacherCourseItem:
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: str          # 'active' | 'inactive'
    students_count: int
    active_cases_count: int  # V1: siempre 0 (Assignment no tiene course_id aún)


def list_teacher_courses(db: Session, actor: CurrentActor) -> list[TeacherCourseItem]:
    """
    Devuelve cursos donde teacher_membership_id corresponde al docente autenticado.
    Incluye conteo de estudiantes (CourseMembership).

    DATA FLOW:
      actor.auth_user_id → Membership(role='teacher', status='active')
      → Course(teacher_membership_id=membership.id)
      → CourseMembership COUNT por curso
    """
    membership = db.execute(
        select(Membership).where(
            Membership.user_id == actor.auth_user_id,
            Membership.role == "teacher",
            Membership.status == "active",
        )
    ).scalar_one_or_none()

    if membership is None:
        return []

    courses = db.execute(
        select(Course).where(
            Course.teacher_membership_id == membership.id
        ).order_by(Course.title)
    ).scalars().all()

    if not courses:
        return []

    course_ids = [c.id for c in courses]

    # Conteo de estudiantes en un solo query (evitar N+1)
    student_counts: dict[str, int] = {}
    rows = db.execute(
        select(CourseMembership.course_id, func.count().label("cnt"))
        .where(CourseMembership.course_id.in_(course_ids))
        .group_by(CourseMembership.course_id)
    ).all()
    for row in rows:
        student_counts[row.course_id] = row.cnt

    return [
        TeacherCourseItem(
            id=c.id,
            title=c.title,
            code=c.code,
            semester=c.semester,
            academic_level=c.academic_level,
            status=c.status,
            students_count=student_counts.get(c.id, 0),
            active_cases_count=0,  # placeholder V1
        )
        for c in courses
    ]
```

> **Nota V1**: `active_cases_count=0` porque `Assignment` no tiene `course_id` en el schema actual.
> El campo queda en la respuesta para conectar en una fase futura sin cambios de contrato.

### `teacher_router.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .database import get_db
from .auth import require_teacher_actor, CurrentActor
from .teacher_reads import list_teacher_courses

teacher_router = APIRouter(prefix="/api/teacher", tags=["teacher"])


class TeacherCourseItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: str
    students_count: int
    active_cases_count: int


class TeacherCoursesResponse(BaseModel):
    courses: list[TeacherCourseItemResponse]
    total: int


@teacher_router.get("/courses", response_model=TeacherCoursesResponse)
def get_teacher_courses(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_teacher_actor),
) -> TeacherCoursesResponse:
    courses = list_teacher_courses(db, actor)
    return TeacherCoursesResponse(
        courses=[TeacherCourseItemResponse(**vars(c)) for c in courses],
        total=len(courses),
    )
```

### `app.py` — registrar router

```python
from .teacher_router import teacher_router
app.include_router(teacher_router)
```

### Criterios de aceptación

- [ ] `GET /api/teacher/courses` con token de docente → 200 con lista de cursos
- [ ] Solo devuelve cursos del docente autenticado (no los de otros docentes)
- [ ] `students_count` refleja el conteo real de `CourseMembership` del curso
- [ ] Docente sin cursos asignados → `{ courses: [], total: 0 }` (no 500)
- [ ] Sin membresía de docente activa → `{ courses: [], total: 0 }` (no 500)
- [ ] Request sin token → 401
- [ ] Request con token de rol `student` o `university_admin` → 403
- [ ] `uv run --directory backend pytest -q` pasa en verde

### Dependencias
Ninguna — primer issue del plan.

---

## Issue 2 — [Backend] Migración `deadline` en `Assignment` + `GET /api/teacher/cases`

### Resumen
El modelo `Assignment` no tiene el campo `deadline`. Este issue agrega la columna vía migración Alembic, persiste `dueAt` del intake payload, e implementa `GET /api/teacher/cases` que filtra casos activos por docente con `deadline >= now()`.

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `backend/alembic/versions/XXXX_add_deadline_to_assignments.py` |
| MODIFICAR | `backend/src/shared/teacher_reads.py` |
| MODIFICAR | `backend/src/shared/teacher_router.py` |
| MODIFICAR | `backend/src/shared/app.py` (handler `POST /api/authoring/jobs`) |

### Migración Alembic

```python
"""add deadline to assignments

Revision ID: XXXX
Revises: c2f8a58d6d1e  (Issue 86: Teacher Directory — ver alembic/versions/)
"""
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assignments", "deadline")
```

### Persistir `dueAt` en el handler de authoring jobs (`app.py`)

Buscar la sección donde se crea el `Assignment` en el handler `POST /api/authoring/jobs`:

```python
# Agregar al crear Assignment:
assignment = Assignment(
    ...
    deadline=intake_request.due_at,   # mapear dueAt del form → deadline
)
```

Verificar la estructura de `IntakeRequest` y agregar `due_at: datetime | None = None` si no existe.

### Agregar a `teacher_reads.py`

```python
from datetime import datetime, timezone
from .models import Assignment
from .auth import ensure_legacy_teacher_bridge


@dataclass
class TeacherCaseItem:
    id: str
    title: str
    deadline: datetime | None
    status: str
    course_codes: list[str]   # V1: siempre [] (Assignment sin course_id)


def list_teacher_active_cases(db: Session, actor: CurrentActor) -> list[TeacherCaseItem]:
    """
    Devuelve Assignment del docente con deadline >= now(), ASC por deadline.

    DATA FLOW:
      actor → ensure_legacy_teacher_bridge → User.id
      → Assignment(teacher_id=user.id, deadline >= now())
      → ORDER BY deadline ASC
    """
    legacy_user = ensure_legacy_teacher_bridge(db, actor)
    now = datetime.now(timezone.utc)

    assignments = db.execute(
        select(Assignment)
        .where(
            Assignment.teacher_id == legacy_user.id,
            Assignment.deadline >= now,
        )
        .order_by(Assignment.deadline.asc())
    ).scalars().all()

    return [
        TeacherCaseItem(
            id=a.id,
            title=a.title,
            deadline=a.deadline,
            status=a.status,
            course_codes=[],   # V1 placeholder
        )
        for a in assignments
    ]
```

### Agregar a `teacher_router.py`

```python
from datetime import datetime
from .teacher_reads import list_teacher_active_cases


class TeacherCaseItemResponse(BaseModel):
    id: str
    title: str
    deadline: datetime | None
    status: str
    course_codes: list[str]
    days_remaining: int | None   # calculado en backend


class TeacherCasesResponse(BaseModel):
    cases: list[TeacherCaseItemResponse]
    total: int


@teacher_router.get("/cases", response_model=TeacherCasesResponse)
def get_teacher_cases(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_teacher_actor),
) -> TeacherCasesResponse:
    from datetime import timezone
    now = datetime.now(timezone.utc)
    cases = list_teacher_active_cases(db, actor)

    items = []
    for c in cases:
        days = None
        if c.deadline:
            delta = c.deadline - now
            days = max(0, delta.days)
        items.append(
            TeacherCaseItemResponse(
                id=c.id,
                title=c.title,
                deadline=c.deadline,
                status=c.status,
                course_codes=c.course_codes,
                days_remaining=days,
            )
        )
    return TeacherCasesResponse(cases=items, total=len(items))
```

### Criterios de aceptación

- [ ] Migración aplica sin errores: `uv run --directory backend alembic upgrade head`
- [ ] `GET /api/teacher/cases` con token válido → 200 con lista de casos
- [ ] Solo incluye casos con `deadline >= now()` (vencidos excluidos)
- [ ] `days_remaining` es entero ≥ 0 (nunca negativo). Si `deadline` es null → `days_remaining: null`
- [ ] Ordenados por deadline ascendente (más urgente primero)
- [ ] `POST /api/authoring/jobs` persiste `dueAt` en `Assignment.deadline`
- [ ] Docente sin casos activos → `{ cases: [], total: 0 }`
- [ ] Request sin token → 401
- [ ] `uv run --directory backend pytest -q` pasa en verde

### ⚠️ Orden de deploy obligatorio
```
1. Aplicar migración Alembic
2. Deployar backend
3. Deployar frontend
```
El campo `deadline` debe existir en DB antes de que el endpoint sea accesible.

### Dependencias
Issue 1 (teacher_router.py debe existir)

---

## Issue 3 — [Frontend] Routing, Scaffolding y RootRedirect

### Resumen
Crear la estructura de carpetas del feature `teacher-dashboard`, registrar la ruta `/teacher/dashboard` en `App.tsx` (ANTES del catch-all `/teacher/*`), actualizar `RootRedirect` para que los docentes aterricen en `/teacher/dashboard`, y suprimir el `SiteHeader` global para esa ruta.

### Archivos

| Acción | Ruta |
|---|---|
| MODIFICAR | `frontend/src/app/App.tsx` |
| MODIFICAR | `frontend/src/app/auth/RootRedirect.tsx` |
| CREAR | `frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx` |

### `App.tsx` — tres cambios

```tsx
// 1. Importar lazy component (junto a los demás imports lazy al inicio)
const TeacherDashboardPage = lazy(() =>
    import("@/features/teacher-dashboard/TeacherDashboardPage").then(
        (module) => ({ default: module.TeacherDashboardPage }),
    ),
);

// 2. Actualizar lógica SiteHeader (agregar teacher dashboard):
const isAdminDashboardRoute = location.pathname.startsWith("/admin/dashboard");
const isTeacherDashboardRoute = location.pathname === "/teacher/dashboard";
// ...
{!isAdminDashboardRoute && !isTeacherDashboardRoute && <SiteHeader />}

// 3. Agregar ruta ANTES de /teacher/* (el catch-all existente):
<Route
    path="/teacher/dashboard"
    element={
        <RequireRole role="teacher">
            <TeacherDashboardPage showToast={showToast} />
        </RequireRole>
    }
/>
// El catch-all /teacher/* permanece sin cambios
```

### `RootRedirect.tsx` — una línea

```tsx
// Cambiar:
case "teacher":
    return <Navigate to="/teacher" replace />;

// Por:
case "teacher":
    return <Navigate to="/teacher/dashboard" replace />;
```

### `TeacherDashboardPage.tsx` — shell inicial

```tsx
import type { ShowToast } from "@/shared/Toast";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({ showToast }: TeacherDashboardPageProps) {
    return (
        <div className="min-h-screen" style={{ background: "#F0F4F8" }}>
            {/* Componentes ensamblados en Issues 5-8 */}
            <p className="p-8 text-sm text-slate-500">Teacher Dashboard — WIP</p>
        </div>
    );
}
```

### Criterios de aceptación

- [ ] Docente autenticado que visita `/` es redirigido a `/teacher/dashboard`
- [ ] `/teacher/dashboard` renderiza sin `SiteHeader` global
- [ ] `/teacher/dashboard` protegido por `<RequireRole role="teacher">` — sin token → redirige a login
- [ ] El catch-all `/teacher/*` sigue funcionando (AuthoringForm accesible en `/teacher`)
- [ ] Estudiante o admin que intente `/teacher/dashboard` → bloqueado por `RequireRole`
- [ ] `npm --prefix frontend run build` sin errores TypeScript

### Dependencias
Ninguna — puede ejecutarse en paralelo con Issues 1 y 2.

---

## Issue 4 — [Frontend] TanStack Query: `queryKeys`, `api.ts` y hooks

### Resumen
Extender la fábrica de query keys con namespace `teacher`, agregar `api.teacher.getCourses()` y `api.teacher.getCases()` al cliente centralizado, y crear el hook `useTeacherDashboard.ts` que encapsula ambas queries.

### Archivos

| Acción | Ruta |
|---|---|
| MODIFICAR | `frontend/src/shared/queryKeys.ts` |
| MODIFICAR | `frontend/src/shared/api.ts` |
| CREAR | `frontend/src/features/teacher-dashboard/useTeacherDashboard.ts` |

### `queryKeys.ts` — agregar namespace `teacher`

```typescript
export const queryKeys = {
    auth: { ... },      // sin cambios
    admin: { ... },     // sin cambios
    authoring: { ... }, // sin cambios
    teacher: {
        /** ["teacher"] — key raíz para invalidación masiva */
        all: () => ["teacher"] as const,
        /** ["teacher", "courses"] — cursos del docente autenticado */
        courses: () => ["teacher", "courses"] as const,
        /** ["teacher", "cases"] — casos activos con deadline >= now */
        cases: () => ["teacher", "cases"] as const,
    },
} as const;
```

### `api.ts` — tipos y namespace `api.teacher`

```typescript
// ─── Types (agregar a adam-types.ts o inline en api.ts, seguir convención existente) ───

export interface TeacherCourseItem {
    id: string;
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    status: "active" | "inactive";
    students_count: number;
    active_cases_count: number;
}

export interface TeacherCoursesResponse {
    courses: TeacherCourseItem[];
    total: number;
}

export interface TeacherCaseItem {
    id: string;
    title: string;
    deadline: string | null;       // ISO 8601 string
    status: string;
    course_codes: string[];
    days_remaining: number | null;
}

export interface TeacherCasesResponse {
    cases: TeacherCaseItem[];
    total: number;
}

// ─── Dentro del objeto api (seguir patrón exacto de api.admin.*) ───

teacher: {
    getCourses: async (): Promise<TeacherCoursesResponse> =>
        parseJsonResponse<TeacherCoursesResponse>("/api/teacher/courses", {
            method: "GET",
            headers: await createAuthorizedHeaders(),
        }),

    getCases: async (): Promise<TeacherCasesResponse> =>
        parseJsonResponse<TeacherCasesResponse>("/api/teacher/cases", {
            method: "GET",
            headers: await createAuthorizedHeaders(),
        }),
},
```

### `useTeacherDashboard.ts`

```typescript
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/shared/queryKeys";
import { api } from "@/shared/api";

export function useTeacherCourses() {
    return useQuery({
        queryKey: queryKeys.teacher.courses(),
        queryFn: () => api.teacher.getCourses(),
        staleTime: 30_000,
        refetchOnWindowFocus: "always",
    });
}

export function useTeacherCases() {
    return useQuery({
        queryKey: queryKeys.teacher.cases(),
        queryFn: () => api.teacher.getCases(),
        staleTime: 30_000,
        refetchOnWindowFocus: "always",
        refetchInterval: 60_000,          // deadlines cambian en tiempo real
        refetchIntervalInBackground: false,
    });
}
```

### Criterios de aceptación

- [ ] `queryKeys.teacher.courses()` retorna `["teacher", "courses"] as const`
- [ ] `queryKeys.teacher.cases()` retorna `["teacher", "cases"] as const`
- [ ] `api.teacher.getCourses()` → `GET /api/teacher/courses` con `Authorization` header
- [ ] `api.teacher.getCases()` → `GET /api/teacher/cases` con `Authorization` header
- [ ] `useTeacherCases` refetchea cada 60 segundos (no en background)
- [ ] `npm --prefix frontend run build` sin errores TypeScript

### Dependencias
Issue 3 (TeacherDashboardPage.tsx debe existir)

---

## Issue 5 — [Frontend] Componente `DashboardHeader`

### Resumen
Header del portal docente pixel-perfect con el mockup. Gradiente azul, logo ADAM, notificaciones, avatar con iniciales del actor, nombre y rol del docente.

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `frontend/src/features/teacher-dashboard/DashboardHeader.tsx` |
| MODIFICAR | `frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx` |

### Especificaciones de diseño

| Elemento | Valor exacto del mockup |
|---|---|
| Gradiente | `linear-gradient(135deg, #0144a0 0%, #0255c5 100%)` |
| Altura | `80px` |
| Container | `max-w-6xl mx-auto px-6` |
| Avatar | `44×44px`, `border: 2px solid rgba(255,255,255,0.35)`, `bg-white/20` |
| Notification dot | `8×8px`, `bg-red-400`, `rounded-full`, `absolute top-2 right-2` |
| Texto nombre | `15px`, `font-semibold`, `text-white` |
| Subtítulo rol | `text-xs`, `text-blue-200` — literal: `"Docente · Facultad de Administración"` |

```tsx
// DashboardHeader.tsx
import { useAuth } from "@/app/auth/useAuth";
import { Bell } from "lucide-react";

function getInitials(fullName: string): string {
    return fullName
        .split(" ")
        .filter(Boolean)
        .slice(0, 2)
        .map((w) => w[0].toUpperCase())
        .join("");
}

export function DashboardHeader() {
    const { actor } = useAuth();
    const fullName = actor?.profile?.full_name ?? "Docente";
    const initials = getInitials(fullName);

    return (
        <header
            style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)", height: "80px" }}
            className="w-full"
        >
            <div className="mx-auto flex h-full max-w-6xl items-center justify-between px-6">
                {/* Logo */}
                <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/20">
                        <svg className="h-5 w-5 text-white" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                        </svg>
                    </div>
                    <div>
                        <p className="text-lg font-bold text-white">ADAM</p>
                        <p className="text-xs text-blue-200">Diseñador de Casos</p>
                    </div>
                </div>

                {/* Controls */}
                <div className="flex items-center gap-3">
                    <button
                        aria-label="Notificaciones"
                        className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 text-white transition-colors hover:bg-white/20"
                    >
                        <Bell className="h-5 w-5" />
                        <span aria-hidden className="absolute right-2 top-2 h-2 w-2 rounded-full bg-red-400" />
                    </button>
                    <div className="h-8 w-px bg-white/20" />
                    <div className="flex items-center gap-3">
                        <div
                            style={{ width: 44, height: 44, border: "2px solid rgba(255,255,255,0.35)" }}
                            className="flex shrink-0 items-center justify-center rounded-full bg-white/20 text-[15px] font-extrabold text-white"
                        >
                            {initials}
                        </div>
                        <div className="hidden sm:block">
                            <p className="text-[15px] font-semibold text-white">{fullName}</p>
                            <p className="text-xs text-blue-200">Docente · Facultad de Administración</p>
                        </div>
                    </div>
                </div>
            </div>
        </header>
    );
}
```

### Criterios de aceptación

- [ ] Gradiente exacto: `#0144a0 → #0255c5` en 135deg
- [ ] Altura exacta 80px
- [ ] Avatar muestra las iniciales de `actor.profile.full_name` (máx. 2 letras)
- [ ] Nombre y rol visibles en `sm:` (ocultos en mobile)
- [ ] Bell button con punto rojo visible
- [ ] `aria-label="Notificaciones"` en el botón bell
- [ ] Punto decorativo del bell es `aria-hidden`

### Dependencias
Issues 3 y 4.

---

## Issue 6 — [Frontend] Sección Quick Actions (3 tarjetas superiores)

### Resumen
Las 3 tarjetas de acción rápida con gradientes, íconos Lucide, y comportamientos definidos: navegar al authoring, scroll suave a la tabla, y toast "Próximamente".

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `frontend/src/features/teacher-dashboard/QuickActionsSection.tsx` |
| MODIFICAR | `frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx` |

### Especificaciones de diseño

| Tarjeta | Gradiente exacto | Ícono (Lucide) | Acción |
|---|---|---|---|
| Crear Nuevo Caso | `from-cyan-500 via-blue-500 to-blue-700` | `Sparkles` | `navigate('/teacher')` |
| Gestión de Casos | `from-violet-500 via-indigo-500 to-indigo-700` | `Briefcase` | `scrollIntoView('#cases-section', {behavior:'smooth'})` |
| Reportes Globales | `from-emerald-500 via-teal-500 to-teal-700` | `BarChart2` | `showToast("Próximamente", "default")` |

```
Propiedades comunes de cada tarjeta:
  height: 100px
  border-radius: 16px
  text: white
  hover: scale-[1.02] + shadow-2xl
  top accent line: h-px gradient from-white/40 to-transparent
  icon button: w-11 h-11, bg-white/20, rounded-xl
  decorative blur circles: aria-hidden
```

### Criterios de aceptación

- [ ] 3 tarjetas con gradientes exactos del mockup
- [ ] "Crear Nuevo Caso" → navega a `/teacher`
- [ ] "Gestión de Casos" → smooth scroll a `#cases-section` (sin cambiar URL)
- [ ] "Reportes Globales" → showToast no bloqueante con "Próximamente"
- [ ] Grid `grid-cols-1 md:grid-cols-3 gap-5`
- [ ] Hover: `scale-[1.02]` + shadow aumentada
- [ ] Elementos decorativos son `aria-hidden`

### Dependencias
Issues 3 y 4.

---

## Issue 7 — [Frontend] Sección Cursos Activos

### Resumen
Sección con tarjetas de curso status-aware, 3 stat pills (estudiantes / casos asignados / promedio), búsqueda client-side, estados de carga/error/vacío, y animaciones escalonadas.

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `frontend/src/features/teacher-dashboard/CursosActivosSection.tsx` |
| MODIFICAR | `frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx` |

### Especificaciones de diseño de la tarjeta

```
CourseCard
├── Left accent bar (5px ancho, border-radius heredado)
│   ├── active:   linear-gradient(to bottom, #0144a0, #60a5fa)
│   └── inactive: #e2e8f0 (gris)
│
├── Content (p-6)
│   ├── StatusBadge
│   │   ├── active:   bg-green-50  text-green-700  border-green-100
│   │   └── inactive: bg-slate-100 text-slate-500  border-slate-200
│   ├── Semestre · Código  (text-[11.5px] text-slate-400)
│   ├── Título del curso   (text-[16px] font-bold text-slate-900)
│   │
│   ├── StatPill × 3  (bg-#f8fafc, border-slate-100, rounded-xl)
│   │   ├── Valor: text-[20px] font-extrabold leading-none text-slate-900
│   │   └── Label: text-[11.5px] font-semibold text-slate-500
│   │   ├── Pill 1: students_count  / "Estudiantes"
│   │   ├── Pill 2: active_cases_count / "Casos asignados"
│   │   └── Pill 3: "—"            / "Promedio"  (siempre — en V1)
│   │
│   └── CTA (border-t border-slate-100 pt-5 mt-5)
│       ├── active:   btn-primary → navigate('/teacher/courses/:id')
│       └── inactive: botón deshabilitado → "Ver historial"

Hover (solo active):
  translateY(-2px)
  border-blue-200
  shadow-[0_12px_40px_-8px_rgba(1,68,160,0.13)]

inactive: opacity-75
```

**CSS animation (agregar en global styles o via `<style>` en el componente):**
```css
@keyframes cardIn {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
}
```
Cada tarjeta: `animation: cardIn 0.35s ease forwards`, `animationDelay: i * 0.07s`, `opacity: 0` inicial.

### Criterios de aceptación

- [ ] Accent bar lateral con color correcto según `status`
- [ ] Pill 1: número real de `students_count`; Pill 2: `active_cases_count` (0 en V1); Pill 3: `"—"`
- [ ] Búsqueda filtra por `course.title` en tiempo real (sin llamada al backend)
- [ ] `status !== "active"` → opacity 75%, botón "Ver historial" deshabilitado
- [ ] `status === "active"` → botón "Entrar al curso" navega a `/teacher/courses/:courseId`
- [ ] Loading → 2 skeleton cards (`animate-pulse h-56`)
- [ ] Error → mensaje de error
- [ ] Vacío → mensaje diferenciado (sin cursos / sin resultados de búsqueda)
- [ ] Grid `grid-cols-1 md:grid-cols-2 gap-6`
- [ ] Animación `cardIn` escalonada por índice

### Dependencias
Issues 3 y 4.

---

## Issue 8 — [Frontend] Sección Casos Activos (tabla + paginación)

### Resumen
Tabla de casos activos del docente paginada client-side (PAGE_SIZE=10). Los 3 botones de acción por fila son placeholders V1 con estructura lista para conectar vistas futuras.

### Archivos

| Acción | Ruta |
|---|---|
| CREAR | `frontend/src/features/teacher-dashboard/CasosActivosSection.tsx` |
| MODIFICAR | `frontend/src/features/teacher-dashboard/TeacherDashboardPage.tsx` |

### Especificaciones de diseño

```
Sección: id="cases-section"  (anchor para scroll del Quick Action)

Table container:
  bg-white, border-[1.5px] border-slate-200, rounded-[18px],
  shadow-sm, overflow-x-auto

Header row (thead):
  background: #0144a0
  text: white, text-[14px], font-bold, tracking-wide
  columnas: Caso | Cursos / Asignaciones | Deadline | Acciones

DeadlineBadge:
  days_remaining <= 5: bg-red-50  text-red-700  border-red-100   (urgente)
  days_remaining >  5: bg-slate-50 text-slate-600 border-slate-100
  days_remaining === 0: mostrar "Hoy"
  days_remaining === null: "Sin fecha" (texto plano gris)

Botones de acción por fila:
  "Ver Caso":   h-9, bg-indigo-50,  text-indigo-600, border-indigo-100
  "Entregas":   h-9, bg-gradient-to-r from-blue-600 to-indigo-600, text-white, shadow-md
  "Editar":     h-9, bg-amber-50,   text-amber-600,  border-amber-100

Table footer:
  bg-slate-50, border-t border-slate-100, px-6 py-4
  texto izq: "Mostrando X de Y casos activos" (text-[12px] uppercase tracking-wider text-slate-400)
  paginación: ChevronLeft + ChevronRight (w-8 h-8), disabled cuando corresponda
```

**Comportamiento de los 3 botones (V1):**
Todos muestran `showToast("Vista disponible próximamente", "default")`.
No navegan a ninguna ruta. La firma de cada función debe incluir el `caso.id` como parámetro
para facilitar la conexión futura sin refactor de la tabla.

```tsx
// Ejemplo estructura lista para futuro:
function CasoRow({ caso, showToast }: CasoRowProps) {
    const handleViewCase = (id: string) => showToast("Vista disponible próximamente", "default");
    const handleDeliverables = (id: string) => showToast("Vista disponible próximamente", "default");
    const handleEdit = (id: string) => showToast("Vista disponible próximamente", "default");
    // ...
    <button onClick={() => handleViewCase(caso.id)}>Ver Caso</button>
    <button onClick={() => handleDeliverables(caso.id)}>Entregas</button>
    <button onClick={() => handleEdit(caso.id)}>Editar</button>
}
```

### Ensamblaje final en `TeacherDashboardPage.tsx`

```tsx
import type { ShowToast } from "@/shared/Toast";
import { DashboardHeader } from "./DashboardHeader";
import { QuickActionsSection } from "./QuickActionsSection";
import { CursosActivosSection } from "./CursosActivosSection";
import { CasosActivosSection } from "./CasosActivosSection";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({ showToast }: TeacherDashboardPageProps) {
    return (
        <div className="min-h-screen" style={{ background: "#F0F4F8" }}>
            <DashboardHeader />
            <main className="mx-auto max-w-6xl space-y-10 px-6 py-9">
                <QuickActionsSection showToast={showToast} />
                <CursosActivosSection />
                <CasosActivosSection showToast={showToast} />
            </main>
        </div>
    );
}
```

### Criterios de aceptación

- [ ] Sección tiene `id="cases-section"` para el anchor scroll
- [ ] Header de tabla con `background: #0144a0`, texto blanco, 4 columnas correctas
- [ ] `DeadlineBadge` rojo para ≤5 días, "Hoy" para 0 días, gris para el resto
- [ ] Los 3 botones muestran toast "Vista disponible próximamente" (no rompen ni redirigen)
- [ ] Paginación client-side PAGE_SIZE=10: prev/next habilitados/deshabilitados correctamente
- [ ] Footer: "Mostrando X de Y casos activos"
- [ ] Botón "Crear nuevo caso" navega a `/teacher`
- [ ] Loading, error y vacío tienen mensajes apropiados
- [ ] `overflow-x-auto` para responsividad en mobile

### Dependencias
Issues 3 y 4. Issues 5, 6, 7 pueden ejecutarse en paralelo.

---

## NOT in Scope (V1)

| Item | Motivo |
|---|---|
| Edicion o calificacion masiva desde el detalle del curso | Issue 205 deja el gradebook como lectura y observabilidad, no como flujo bulk-write |
| Funcionalidad real de Ver Caso / Entregas / Editar | Botones placeholder con toast |
| Paginación server-side de cursos | Volumen esperado < 20 cursos por docente |
| Cálculo real de promedio | Sin sistema de calificaciones en V1 |
| Notificaciones funcionales (bell) | Punto decorativo, sin backend |
| Campo `archivado` en Assignment | No existe en schema — filtro solo por `deadline` |
| Modal de edición de deadline | Requiere vista de caso implementada |
| Soft delete de Assignment | Fuera del scope del dashboard |

---

## What Already Exists (Reúso)

| Componente | Archivo | Reúso en este plan |
|---|---|---|
| `require_teacher_actor` | `backend/src/shared/auth.py` | Dependency en ambos endpoints |
| `ensure_legacy_teacher_bridge` | `backend/src/shared/auth.py` | Usado en `list_teacher_active_cases` |
| `admin_reads.py` | `backend/src/shared/admin_reads.py` | Modelo estructural para `teacher_reads.py` |
| `get_db` | `backend/src/shared/database.py` | Reutilizado sin cambios |
| `queryKeys` factory | `frontend/src/shared/queryKeys.ts` | Extendido con namespace `teacher` |
| `api.ts` client | `frontend/src/shared/api.ts` | Extendido con `api.teacher.*` |
| `useToast()` | `frontend/src/shared/Toast.tsx` | Mismo patrón que AdminDashboardPage |
| `useAuth()` / `actor` | `frontend/src/app/auth/useAuth.ts` | Usado en DashboardHeader para initials |
| `<RequireRole role="teacher">` | `frontend/src/app/auth/RequireRole.tsx` | Wrapping la nueva ruta |
| `AuthoringForm.tsx` | `frontend/src/features/teacher-authoring/` | Sin tocar — solo se enruta hacia él |

---

## Comandos de Verificación

```bash
# Backend
uv run --directory backend alembic upgrade head
uv run --directory backend pytest -q
uv run --directory backend mypy src

# Frontend
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

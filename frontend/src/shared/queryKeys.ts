import type { IntentType, SuggestRequest } from "@/shared/adam-types";

/**
 * Filtros para la lista de cursos del dashboard de administrador.
 *
 * Definido aquí porque no existe como tipo nombrado en el codebase:
 * `buildCourseFilters()` en AdminDashboardPage retornaba un objeto inline.
 * Al moverlo aquí lo compartimos entre el componente y las query keys.
 */
export interface CourseFilters {
    search?: string;
    semester?: string;
    status?: string;
    academic_level?: string;
    page?: number;
    page_size?: number;
}

/**
 * Fábrica centralizada de query keys para toda la aplicación.
 *
 * Convenciones:
 * - Cada key es una función que retorna un array `as const` para type safety.
 * - Las keys más genéricas (ej. `admin.all()`) permiten invalidación en bloque.
 * - Las keys con parámetros opcionales (ej. `courses(f?)`) permiten invalidar
 *   todas las variantes con `queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses() })`.
 *
 * Uso:
 *   useQuery({ queryKey: queryKeys.admin.summary(), queryFn: ... })
 *   queryClient.invalidateQueries({ queryKey: queryKeys.admin.courses() })
 */
export const queryKeys = {
    auth: {
        /** ["auth", "actor"] — perfil del usuario autenticado vía /auth/me */
        actor: () => ["auth", "actor"] as const,
    },
    student: {
        /** ["student"] — key raíz para invalidación masiva */
        all: () => ["student"] as const,
        /** ["student", "courses"] — cursos visibles del estudiante autenticado */
        courses: () => ["student", "courses"] as const,
        /** ["student", "cases"] — casos visibles del estudiante autenticado */
        cases: () => ["student", "cases"] as const,
    },
    admin: {
        /** ["admin"] — key raíz para invalidación masiva (ej. al cerrar sesión) */
        all: () => ["admin"] as const,
        /** ["admin", "summary"] — KPIs del dashboard (cursos activos, docentes, etc.) */
        summary: () => ["admin", "summary"] as const,
        /**
         * ["admin", "courses", filters?] — lista paginada de cursos con filtros.
         * Sin argumentos invalida todas las variantes de la lista.
         */
        courses: (f?: CourseFilters) => {
            if (f === undefined) {
                return ["admin", "courses"] as const;
            }
            return ["admin", "courses", f] as const;
        },
        /** ["admin", "teacher-options"] — opciones para el dropdown de asignación de docente */
        teacherOptions: () => ["admin", "teacher-options"] as const,
        teacherDirectory: () => ["admin", "teacher-directory"] as const,
    },
    authoring: {
        /**
         * ["authoring", "suggest", intent, payload] — sugerencias de IA en el formulario.
         * Mutations fire-and-forget — no se cachean, pero la key permite futuras extensiones.
         */
        suggest: (intent: IntentType, payload: SuggestRequest) =>
            ["authoring", "suggest", intent, payload] as const,
    },
    teacher: {
        /** ["teacher"] — key raíz para invalidación masiva */
        all: () => ["teacher"] as const,
        /** ["teacher", "courses"] — cursos del docente autenticado */
        courses: () => ["teacher", "courses"] as const,
        /** ["teacher", "course", courseId] — detalle compuesto de un curso docente */
        course: (courseId: string) => ["teacher", "course", courseId] as const,
        /** ["teacher", "course-access-link", courseId] — metadata aislada del access link docente */
        accessLink: (courseId: string) => ["teacher", "course-access-link", courseId] as const,
        /** ["teacher", "cases"] — casos activos del docente autenticado */
        cases: () => ["teacher", "cases"] as const,
        /** ["teacher", "case", id] — detalle de un caso del docente */
        case: (id: string) => ["teacher", "case", id] as const,
    },
} as const;

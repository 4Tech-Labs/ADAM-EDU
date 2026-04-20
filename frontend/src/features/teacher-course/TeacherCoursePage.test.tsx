import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "@/app/auth/auth-types";
import { ApiError, api } from "@/shared/api";
import type { TeacherCourseDetailResponse } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

import { TeacherCoursePage } from "./TeacherCoursePage";

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCourseDetail: vi.fn(),
                saveCourseSyllabus: vi.fn(),
            },
        },
    };
});

const showToast = vi.fn();

const teacherAuthValue: AuthContextValue = {
    session: { access_token: "jwt" } as never,
    actor: {
        auth_user_id: "teacher-1",
        profile: { id: "profile-1", full_name: "Laura Gomez" },
        memberships: [
            {
                id: "membership-1",
                university_id: "uni-1",
                role: "teacher",
                status: "active",
                must_rotate_password: false,
            },
        ],
        must_rotate_password: false,
        primary_role: "teacher",
    },
    loading: false,
    error: null,
    signOut: vi.fn(async () => undefined),
    refreshActor: vi.fn(async () => undefined),
};

function LocationSearchProbe() {
    const location = useLocation();
    return <div data-testid="location-search">{location.search}</div>;
}

function createCourseDetailResponse(
    overrides?: Partial<TeacherCourseDetailResponse>,
): TeacherCourseDetailResponse {
    const baseResponse: TeacherCourseDetailResponse = {
        course: {
            id: "course-1",
            title: "Gerencia Estratégica y Modelos de Negocio en Ecosistemas Digitales",
            code: "GTD-GEME-01-2026",
            semester: "2026-I",
            academic_level: "Especialización",
            status: "active",
            max_students: 30,
            students_count: 24,
            active_cases_count: 3,
        },
        syllabus: {
            department: "Gestión de las Organizaciones",
            knowledge_area: "Economía, Administración, Contaduría y afines",
            nbc: "Administración",
            version_label: "1.2 — 17/02/2026",
            academic_load: "3 créditos, 144 horas totales, modalidad virtual, idioma español.",
            course_description:
                "Esta asignatura aborda la evolución de la estrategia corporativa hacia modelos digitales impulsados por IA.",
            general_objective:
                "Formular estrategias de negocio disruptivas en ecosistemas digitales habilitados por IA.",
            specific_objectives: [
                "Analizar plataformas digitales y efectos de red.",
                "Diseñar modelos de negocio con IA agéntica.",
            ],
            modules: [
                {
                    module_id: "module-1",
                    module_title: "Fundamentos de estrategia en la era de la IA",
                    weeks: "1-4",
                    module_summary:
                        "Bases estratégicas para ecosistemas digitales y agentes autónomos.",
                    learning_outcomes: ["Comprender el cambio de paradigma estratégico"],
                    units: [
                        {
                            unit_id: "unit-1",
                            title: "Ecosistemas digitales",
                            topics: "Plataformas, efectos de red y DAOs.",
                        },
                    ],
                    cross_course_connections: "Arquitectura Empresarial",
                },
            ],
            evaluation_strategy: [
                {
                    activity: "Primer parcial",
                    weight: 20,
                    linked_objectives: ["O1"],
                    expected_outcome: "Diagnóstico estratégico sólido",
                },
            ],
            didactic_strategy: {
                methodological_perspective:
                    "Aprendizaje basado en casos con discusión guiada y análisis estratégico.",
                pedagogical_modality:
                    "Sesiones sincrónicas y trabajo autónomo asistido por ADAM.",
            },
            integrative_project:
                "Diseñar una estrategia de transformación digital con IA agéntica para una organización real.",
            bibliography: [
                "Parker, G. G. (2016). Platform Revolution.",
                "Iansiti, M. (2020). Competing in the Age of AI.",
            ],
            teacher_notes: "Mantener foco en gobernanza responsable de IA.",
            ai_grounding_context: {
                course_identity: {
                    course_id: "course-1",
                    course_title:
                        "Gerencia Estratégica y Modelos de Negocio en Ecosistemas Digitales",
                    academic_level: "Especialización",
                    department: "Gestión de las Organizaciones",
                    knowledge_area: "Economía, Administración, Contaduría y afines",
                    nbc: "Administración",
                },
                pedagogical_intent: {
                    course_description:
                        "Esta asignatura aborda la evolución de la estrategia corporativa hacia modelos digitales impulsados por IA.",
                    general_objective:
                        "Formular estrategias de negocio disruptivas en ecosistemas digitales habilitados por IA.",
                    specific_objectives: [
                        "Analizar plataformas digitales y efectos de red.",
                        "Diseñar modelos de negocio con IA agéntica.",
                    ],
                },
                instructional_scope: {
                    modules: [],
                    evaluation_strategy: [],
                    didactic_strategy: {
                        methodological_perspective:
                            "Aprendizaje basado en casos con discusión guiada y análisis estratégico.",
                        pedagogical_modality:
                            "Sesiones sincrónicas y trabajo autónomo asistido por ADAM.",
                    },
                },
                generation_hints: {
                    target_student_profile: "",
                    scenario_constraints: [],
                    preferred_techniques: [],
                    difficulty_signal: "advanced",
                    forbidden_mismatches: ["No ignorar el syllabus vigente."],
                },
                metadata: {
                    syllabus_revision: 1,
                    saved_at: "2026-04-18T18:30:00Z",
                    saved_by_membership_id: "membership-1",
                },
            },
        },
        revision_metadata: {
            current_revision: 1,
            saved_at: "2026-04-18T18:30:00Z",
            saved_by_membership_id: "membership-1",
        },
        configuration: {
            access_link_status: "active",
            access_link_id: "access-link-1",
            access_link_created_at: "2026-04-16T10:00:00Z",
            join_path: "/app/join",
        },
    };

    return {
        ...baseResponse,
        ...overrides,
    };
}

function renderTeacherCoursePage(initialEntry = "/teacher/courses/course-1") {
    return renderWithProviders(
        <>
            <Routes>
                <Route
                    path="/teacher/courses/:courseId"
                    element={<TeacherCoursePage showToast={showToast} />}
                />
            </Routes>
            <LocationSearchProbe />
        </>,
        {
            initialEntries: [initialEntry],
            authValue: teacherAuthValue,
        },
    );
}

describe("TeacherCoursePage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("loads the composed teacher course detail route", async () => {
        vi.mocked(api.teacher.getCourseDetail).mockResolvedValueOnce(
            createCourseDetailResponse(),
        );

        renderTeacherCoursePage();

        expect(
            await screen.findByRole("heading", { name: /Syllabus de la asignatura/i }),
        ).toBeTruthy();
        expect(api.teacher.getCourseDetail).toHaveBeenCalledWith("course-1");
        expect(screen.getByDisplayValue("GTD-GEME-01-2026")).toBeTruthy();
        expect(
            screen.getByDisplayValue("Gestión de las Organizaciones"),
        ).toBeTruthy();
    });

    it("persists the active tab in the URL", async () => {
        vi.mocked(api.teacher.getCourseDetail).mockResolvedValueOnce(
            createCourseDetailResponse(),
        );

        renderTeacherCoursePage();

        await screen.findByRole("heading", { name: /Syllabus de la asignatura/i });
        fireEvent.click(screen.getByRole("tab", { name: "Configuración" }));

        expect(await screen.findByRole("heading", { name: /Configuración del Curso/i })).toBeTruthy();
        expect(screen.getByTestId("location-search")).toHaveTextContent("?tab=configuracion");
    });

    it("saves the syllabus with expected_revision and updates the visible revision metadata", async () => {
        const baseDetail = createCourseDetailResponse();

        vi.mocked(api.teacher.getCourseDetail).mockResolvedValueOnce(
            baseDetail,
        );
        vi.mocked(api.teacher.saveCourseSyllabus).mockResolvedValueOnce(
            createCourseDetailResponse({
                syllabus: {
                    ...baseDetail.syllabus!,
                    department: "Escuela de Negocios Digitales",
                },
                revision_metadata: {
                    current_revision: 2,
                    saved_at: "2026-04-19T14:15:00Z",
                    saved_by_membership_id: "membership-1",
                },
            }),
        );

        renderTeacherCoursePage();

        await screen.findByRole("heading", { name: /Syllabus de la asignatura/i });
        fireEvent.change(screen.getByLabelText("Departamento que la ofrece"), {
            target: { value: "Escuela de Negocios Digitales" },
        });
        fireEvent.click(screen.getAllByRole("button", { name: /Guardar cambios|Guardar y publicar/i })[0]);

        await waitFor(() => {
            expect(api.teacher.saveCourseSyllabus).toHaveBeenCalledWith(
                "course-1",
                expect.objectContaining({
                    expected_revision: 1,
                    syllabus: expect.objectContaining({
                        department: "Escuela de Negocios Digitales",
                    }),
                }),
            );
        });

        expect(showToast).toHaveBeenCalledWith(
            "Syllabus guardado. ADAM usará la versión actualizada en próximas generaciones.",
            "success",
        );
        expect(screen.getAllByText("R2").length).toBeGreaterThan(0);
    });

    it("blocks save on client-side validation failure", async () => {
        vi.mocked(api.teacher.getCourseDetail).mockResolvedValueOnce(
            createCourseDetailResponse(),
        );

        renderTeacherCoursePage();

        await screen.findByRole("heading", { name: /Syllabus de la asignatura/i });
        fireEvent.change(screen.getByLabelText("Departamento que la ofrece"), {
            target: { value: "" },
        });
        fireEvent.click(screen.getAllByRole("button", { name: /Guardar cambios|Guardar y publicar/i })[0]);

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "Completa el departamento que ofrece la asignatura.",
        );
        expect(api.teacher.saveCourseSyllabus).not.toHaveBeenCalled();
    });

    it("handles stale revision conflicts with refetch and clear feedback", async () => {
        const baseDetail = createCourseDetailResponse();

        vi.mocked(api.teacher.getCourseDetail)
            .mockResolvedValueOnce(baseDetail)
            .mockResolvedValueOnce(
                createCourseDetailResponse({
                    revision_metadata: {
                        current_revision: 2,
                        saved_at: "2026-04-19T12:00:00Z",
                        saved_by_membership_id: "membership-9",
                    },
                    syllabus: {
                        ...baseDetail.syllabus!,
                        version_label: "1.3 — 19/04/2026",
                    },
                }),
            );
        vi.mocked(api.teacher.saveCourseSyllabus).mockRejectedValueOnce(
            new ApiError(409, "stale syllabus", "stale_syllabus_revision"),
        );

        renderTeacherCoursePage();

        await screen.findByRole("heading", { name: /Syllabus de la asignatura/i });
        fireEvent.change(screen.getByLabelText("Versión del syllabus"), {
            target: { value: "1.2 — borrador local" },
        });
        fireEvent.click(screen.getAllByRole("button", { name: /Guardar cambios|Guardar y publicar/i })[0]);

        expect(await screen.findByRole("alert")).toHaveTextContent(
            "El syllabus cambió desde tu última carga. Recargamos la versión más reciente para evitar sobrescrituras.",
        );
        await waitFor(() => {
            expect(api.teacher.getCourseDetail).toHaveBeenCalledTimes(2);
        });
        expect(showToast).toHaveBeenCalledWith(
            "El syllabus cambió desde tu última carga. Recargamos la versión más reciente para evitar sobrescrituras.",
            "error",
        );
        expect(screen.getByDisplayValue("1.3 — 19/04/2026")).toBeTruthy();
    });

    it("renders configuration metadata without fake raw-link actions", async () => {
        vi.mocked(api.teacher.getCourseDetail).mockResolvedValueOnce(
            createCourseDetailResponse(),
        );

        renderTeacherCoursePage("/teacher/courses/course-1?tab=configuracion");

        expect(await screen.findByRole("heading", { name: /Configuración del Curso/i })).toBeTruthy();
        expect(screen.getByDisplayValue("access-link-1")).toBeTruthy();
        expect(screen.getByDisplayValue("/app/join")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /copiar/i })).toBeNull();
        expect(screen.queryByRole("button", { name: /regenerar/i })).toBeNull();
    });

    it("shows a page-level error when the detail query fails", async () => {
        vi.mocked(api.teacher.getCourseDetail).mockRejectedValueOnce(
            new ApiError(404, "course not found", "course_not_found"),
        );

        renderTeacherCoursePage();

        expect(await screen.findByTestId("global-page-error")).toBeTruthy();
        expect(
            screen.getByText("El curso ya no existe o no pertenece a tu cuenta docente."),
        ).toBeTruthy();
    });
});

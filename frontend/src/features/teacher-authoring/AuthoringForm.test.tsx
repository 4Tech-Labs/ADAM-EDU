import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/shared/test-utils";
import { server } from "@/shared/testing/msw/server";

import { AuthoringForm } from "./AuthoringForm";
import { FORM_STATE_SESSION_KEY } from "./authoringFormConfig";

type DeferredHttpResponse =
    | ReturnType<typeof HttpResponse.json>
    | ReturnType<typeof HttpResponse.text>;

function createDeferredResponse() {
    let resolve!: (response: DeferredHttpResponse) => void;
    const promise = new Promise<DeferredHttpResponse>((res) => {
        resolve = res;
    });

    return { promise, resolve };
}

async function selectOption(
    user: ReturnType<typeof userEvent.setup>,
    label: RegExp,
    option: RegExp,
) {
    await user.click(screen.getByLabelText(label));
    await user.click(await screen.findByRole("option", { name: option }));
}

async function enableSuggestions(user: ReturnType<typeof userEvent.setup>) {
    await selectOption(user, /asignatura/i, /gerencia/i);
    await user.click(screen.getByLabelText(/grupos destino/i));
    await user.click(await screen.findByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" }));
    await selectOption(user, /m[oó]dulo del syllabus/i, /fundamentos/i);
}

async function showTechniquesSection(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("radio", { name: /caso .*an[aá]lisis de datos/i }));
}

describe("AuthoringForm", () => {
    beforeAll(() => {
        Element.prototype.hasPointerCapture ??= () => false;
        Element.prototype.releasePointerCapture ??= () => {};
        Element.prototype.setPointerCapture ??= () => {};
        Element.prototype.scrollIntoView ??= () => {};
    });

    beforeEach(() => {
        vi.restoreAllMocks();
        server.use(
            http.get("/api/teacher/courses", () => HttpResponse.json({
                courses: [
                    {
                        id: "course-1",
                        title: "Gerencia de Operaciones",
                        code: "GO-101",
                        semester: "2025-1",
                        academic_level: "MBA",
                        status: "active",
                        students_count: 32,
                        active_cases_count: 1,
                    },
                ],
                total: 1,
            })),
            http.get("/api/teacher/courses/:courseId", ({ params }) => {
                if (params.courseId !== "course-1") {
                    return HttpResponse.text("Not found", { status: 404 });
                }

                return HttpResponse.json({
                    course: {
                        id: "course-1",
                        title: "Gerencia de Operaciones",
                        code: "GO-101",
                        semester: "2025-1",
                        academic_level: "MBA",
                        status: "active",
                        max_students: 35,
                        students_count: 32,
                        active_cases_count: 1,
                    },
                    syllabus: {
                        department: "Administracion",
                        knowledge_area: "Operaciones",
                        nbc: "Administracion",
                        version_label: "v1",
                        academic_load: "48 horas",
                        course_description: "Curso de operaciones",
                        general_objective: "Tomar decisiones operativas",
                        specific_objectives: ["Analizar capacidad"],
                        modules: [
                            {
                                module_id: "module-1",
                                module_title: "Fundamentos de Operaciones",
                                weeks: "1-4",
                                module_summary: "Base conceptual",
                                learning_outcomes: ["Diagnosticar procesos"],
                                units: [
                                    {
                                        unit_id: "unit-1",
                                        title: "Pronosticos",
                                        topics: "Series de tiempo",
                                    },
                                ],
                                cross_course_connections: "Finanzas",
                            },
                        ],
                        evaluation_strategy: [],
                        didactic_strategy: {
                            methodological_perspective: "Aplicada",
                            pedagogical_modality: "Presencial",
                        },
                        integrative_project: "Proyecto final",
                        bibliography: ["Libro 1"],
                        teacher_notes: "",
                        ai_grounding_context: {
                            course_identity: {
                                course_id: "course-1",
                                course_title: "Gerencia de Operaciones",
                                academic_level: "MBA",
                                department: "Administracion",
                                knowledge_area: "Operaciones",
                                nbc: "Administracion",
                            },
                            pedagogical_intent: {
                                course_description: "Curso de operaciones",
                                general_objective: "Tomar decisiones operativas",
                                specific_objectives: ["Analizar capacidad"],
                            },
                            instructional_scope: {
                                modules: [
                                    {
                                        module_id: "module-1",
                                        module_title: "Fundamentos de Operaciones",
                                        weeks: "1-4",
                                        module_summary: "Base conceptual",
                                        learning_outcomes: ["Diagnosticar procesos"],
                                        units: [
                                            {
                                                unit_id: "unit-1",
                                                title: "Pronosticos",
                                                topics: "Series de tiempo",
                                            },
                                        ],
                                        cross_course_connections: "Finanzas",
                                    },
                                ],
                                evaluation_strategy: [],
                                didactic_strategy: {
                                    methodological_perspective: "Aplicada",
                                    pedagogical_modality: "Presencial",
                                },
                            },
                            generation_hints: {
                                target_student_profile: "business",
                                scenario_constraints: ["Use datos reales"],
                                preferred_techniques: ["Arbol de decision"],
                                difficulty_signal: "intermediate",
                                forbidden_mismatches: [],
                            },
                            metadata: {
                                syllabus_revision: 3,
                                saved_at: "2025-02-01T00:00:00Z",
                                saved_by_membership_id: "membership-1",
                            },
                        },
                    },
                    revision_metadata: {
                        current_revision: 3,
                        saved_at: "2025-02-01T00:00:00Z",
                        saved_by_membership_id: "membership-1",
                    },
                    configuration: {
                        access_link_status: "active",
                        access_link_id: "link-1",
                        access_link_created_at: "2025-02-01T00:00:00Z",
                        join_path: "/c/course-1/join",
                    },
                });
            }),
            http.get("/api/authoring/algorithm-catalog", () =>
                HttpResponse.json({
                    profile: "business",
                    case_type: "harvard_with_eda",
                    items: [
                        { name: "Regresión Lineal", family: "regresion", family_label: "Regresión", tier: "baseline" },
                        { name: "Árboles de decisión", family: "clasificacion", family_label: "Clasificación", tier: "baseline" },
                    ],
                }),
            ),
        );
    });

    it("fills scenario fields from the scenario mutation and shows loading state", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", async () => deferred.promise),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Escenario sugerido",
                guidingQuestion: "Pregunta sugerida",
                suggestedTechniques: [],
            }),
        );

        expect(await screen.findByDisplayValue("Escenario sugerido")).toBeInTheDocument();
        expect(screen.getByDisplayValue("Pregunta sugerida")).toBeInTheDocument();
    }, 20_000);

    it("fills algorithm picks from the techniques mutation (Issue #230)", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", async ({ request }) => {
                const body = (await request.json()) as { intent: string };
                if (body.intent === "techniques") {
                    return deferred.promise;
                }

                return HttpResponse.json({
                    scenarioDescription: "",
                    guidingQuestion: "",
                    suggestedTechniques: [],
                });
            }),
            http.get("/api/authoring/algorithm-catalog", () =>
                HttpResponse.json({
                    profile: "business",
                    case_type: "harvard_with_eda",
                    items: [
                        { name: "Regresión Lineal", family: "regresion", family_label: "Regresión", tier: "baseline" },
                        { name: "Árboles de decisión", family: "clasificacion", family_label: "Clasificación", tier: "baseline" },
                    ],
                }),
            ),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);
        await showTechniquesSection(user);

        const button = await screen.findByRole("button", { name: /sugerir algoritmos con adam/i });
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "",
                guidingQuestion: "",
                suggestedTechniques: ["Árboles de decisión"],
                algorithmPrimary: "Árboles de decisión",
                algorithmChallenger: null,
            }),
        );

        // Baseline dropdown trigger should reflect the chosen primary.
        await waitFor(() => {
            expect(screen.getByLabelText(/algoritmo principal/i)).toHaveTextContent(/árboles de decisión/i);
        });
    }, 20_000);

    it("prevents duplicate scenario requests on rapid double click", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();
        const requestCounter = vi.fn(() => deferred.promise);

        server.use(
            http.post("/api/suggest", () => requestCounter()),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });
        expect(requestCounter).toHaveBeenCalledTimes(1);

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Escenario único",
                guidingQuestion: "Pregunta única",
                suggestedTechniques: [],
            }),
        );

        expect(await screen.findByDisplayValue("Escenario único")).toBeInTheDocument();
    });

    it("shows the mutation error and re-enables the button after failure", async () => {
        const user = userEvent.setup();

        server.use(
            http.post("/api/suggest", () => HttpResponse.text("Fallo de red controlado", { status: 500 })),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);

        expect(await screen.findByText(/fallo de red controlado/i)).toBeInTheDocument();
        await waitFor(() => {
            expect(button).not.toBeDisabled();
        });
    });

    it("ignores a stale scenario response after the teacher changes context", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", () => deferred.promise),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        await selectOption(user, /industria/i, /retail/i);

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Respuesta vieja",
                guidingQuestion: "Pregunta vieja",
                suggestedTechniques: [],
            }),
        );

        await waitFor(() => {
            expect(screen.queryByDisplayValue("Respuesta vieja")).not.toBeInTheDocument();
        });
        expect(screen.getByLabelText(/industria/i)).toHaveTextContent(/retail/i);
    }, 20_000);

    it("ignores a stale response after clearing the form and resets visible mutation errors", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();
        let requestCount = 0;

        server.use(
            http.post("/api/suggest", () => {
                requestCount += 1;
                if (requestCount === 1) {
                    return HttpResponse.text("Error transitorio", { status: 500 });
                }
                return deferred.promise;
            }),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        expect(await screen.findByText(/error transitorio/i)).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: /limpiar todo/i }));
        await waitFor(() => {
            expect(screen.queryByText(/error transitorio/i)).not.toBeInTheDocument();
        });

        await enableSuggestions(user);
        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        await user.click(screen.getByRole("button", { name: /limpiar todo/i }));

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "No debe aplicar",
                guidingQuestion: "No debe aplicar",
                suggestedTechniques: [],
            }),
        );

        await waitFor(() => {
            expect(screen.queryByDisplayValue("No debe aplicar")).not.toBeInTheDocument();
        });
    }, 20_000);
});

describe("GroupsCombobox (within AuthoringForm)", () => {
    beforeAll(() => {
        Element.prototype.hasPointerCapture ??= () => false;
        Element.prototype.releasePointerCapture ??= () => {};
        Element.prototype.setPointerCapture ??= () => {};
        Element.prototype.scrollIntoView ??= () => {};
    });

    beforeEach(() => {
        vi.restoreAllMocks();
        server.use(
            http.get("/api/teacher/courses", () => HttpResponse.json({
                courses: [
                    {
                        id: "course-1",
                        title: "Gerencia de Operaciones",
                        code: "GO-101",
                        semester: "2025-1",
                        academic_level: "MBA",
                        status: "active",
                        students_count: 32,
                        active_cases_count: 1,
                    },
                ],
                total: 1,
            })),
        );
    });

    it("opens the popover and lists available courses", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await user.click(screen.getByLabelText(/grupos destino/i));

        expect(await screen.findByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" })).toBeInTheDocument();
    });

    it("shows empty state when teacher has no courses", async () => {
        server.use(
            http.get("/api/teacher/courses", () => HttpResponse.json({ courses: [], total: 0 })),
        );
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await user.click(screen.getByLabelText(/grupos destino/i));

        expect(await screen.findByText(/no tienes cursos disponibles/i)).toBeInTheDocument();
    });

    it("clicking a course option adds a chip and does NOT submit the form", async () => {
        const user = userEvent.setup();
        const onSubmit = vi.fn();
        renderWithProviders(<AuthoringForm onSubmit={onSubmit} />);

        await user.click(screen.getByLabelText(/grupos destino/i));
        await user.click(await screen.findByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" }));

        expect(screen.getByText("Gerencia de Operaciones (GO-101)")).toBeInTheDocument();
        expect(onSubmit).not.toHaveBeenCalled();
    });

    it("selected course no longer appears as an available option", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await user.click(screen.getByLabelText(/grupos destino/i));
        await user.click(await screen.findByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" }));

        // Trigger reflects the selection
        expect(screen.getByText(/1 grupo seleccionado/i)).toBeInTheDocument();

        // Re-open: the course now appears in the selected section only, not as an addable option
        await user.click(screen.getByLabelText(/grupos destino/i));
        expect(screen.queryByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Quitar selección Gerencia de Operaciones (GO-101)" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Quitar grupo Gerencia de Operaciones (GO-101)" })).toBeInTheDocument();
    });

    it("clicking the chip removes the selection", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        // Add the course
        await user.click(screen.getByLabelText(/grupos destino/i));
        await user.click(await screen.findByRole("button", { name: "Agregar grupo Gerencia de Operaciones (GO-101)" }));

        // Chip should now be visible (popover closed after selection)
        const chip = screen.getByRole("button", { name: "Quitar grupo Gerencia de Operaciones (GO-101)" });
        await user.click(chip);

        expect(screen.queryByText("Gerencia de Operaciones (GO-101)")).not.toBeInTheDocument();
    });
});

// ─── Shared MSW setup helpers for the new describe blocks ───────────────────

const baseCoursesHandler = http.get("/api/teacher/courses", () =>
    HttpResponse.json({
        courses: [{
            id: "course-1", title: "Gerencia de Operaciones", code: "GO-101",
            semester: "2025-1", academic_level: "MBA", status: "active",
            students_count: 32, active_cases_count: 1,
        }],
        total: 1,
    }),
);

const baseCourseDetailHandler = http.get("/api/teacher/courses/:courseId", () =>
    HttpResponse.json({
        course: {
            id: "course-1", title: "Gerencia de Operaciones", code: "GO-101",
            semester: "2025-1", academic_level: "MBA", status: "active",
            max_students: 35, students_count: 32, active_cases_count: 1,
        },
        syllabus: {
            department: "Administracion", knowledge_area: "Operaciones",
            nbc: "Administracion", version_label: "v1", academic_load: "48 horas",
            course_description: "Curso", general_objective: "Obj",
            specific_objectives: [], evaluation_strategy: [],
            didactic_strategy: { methodological_perspective: "Aplicada", pedagogical_modality: "Presencial" },
            integrative_project: "", bibliography: [], teacher_notes: "",
            ai_grounding_context: {
                course_identity: {
                    course_id: "course-1", course_title: "Gerencia de Operaciones",
                    academic_level: "MBA", department: "Administracion",
                    knowledge_area: "Operaciones", nbc: "Administracion",
                },
                pedagogical_intent: { general_objective: "Obj", specific_objectives: [] },
                curriculum_scope: { coverage_signal: "focused" },
            },
            modules: [{
                module_id: "module-1",
                module_title: "Fundamentos de Operaciones",
                weeks: "1-4",
                module_summary: "Base conceptual",
                learning_outcomes: [],
                units: [{ unit_id: "unit-1", title: "Pronosticos", topics: "Series de tiempo" }],
                cross_course_connections: "",
            }],
        },
    }),
);

// ─── Task 1 — Required fields & disabled submit button ───────────────────────

describe("Task 1 — Required fields and disabled submit button", () => {
    beforeAll(() => {
        Element.prototype.hasPointerCapture ??= () => false;
        Element.prototype.releasePointerCapture ??= () => {};
        Element.prototype.setPointerCapture ??= () => {};
        Element.prototype.scrollIntoView ??= () => {};
    });

    beforeEach(() => {
        vi.restoreAllMocks();
        server.use(baseCoursesHandler, baseCourseDetailHandler);
    });

    it("submit button is disabled on initial render", () => {
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        expect(screen.getByRole("button", { name: /generar caso harvard/i })).toBeDisabled();
    });

    it("submit button is enabled after all required fields are filled", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        await selectOption(user, /unidad tem/i, /pronosticos/i);
        fireEvent.change(screen.getByRole("textbox", { name: /descripci[oó]n/i }), { target: { value: "Escenario completo de prueba" } });
        fireEvent.change(screen.getByLabelText(/pregunta gu[ií]a/i), { target: { value: "¿Qué decisión tomar?" } });
        fireEvent.change(screen.getByLabelText(/disponibilidad/i), { target: { value: "2025-06-01T00:00" } });
        fireEvent.change(screen.getByLabelText(/fecha de cierre/i), { target: { value: "2025-07-01T00:00" } });

        await waitFor(() => {
            expect(screen.getByRole("button", { name: /generar caso harvard/i })).not.toBeDisabled();
        });
    }, 15_000);

    it("handleSubmit shows topicUnit error when module has units and no unit is selected", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        // Do NOT select a topicUnit — bypass disabled button via fireEvent.submit
        fireEvent.submit(document.querySelector("form")!);

        await waitFor(() => {
            expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
        });
    });

    it("handleSubmit shows availableFrom error when date is not set", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        await selectOption(user, /unidad tem/i, /pronosticos/i);
        await user.type(screen.getByRole("textbox", { name: /descripci[oó]n/i }), "Escenario");
        await user.type(screen.getByLabelText(/pregunta gu[ií]a/i), "Pregunta");
        fireEvent.change(screen.getByLabelText(/fecha de cierre/i), { target: { value: "2025-07-01T00:00" } });
        // availableFrom intentionally left empty
        fireEvent.submit(document.querySelector("form")!);

        await waitFor(() => {
            expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
        });
    });

    it("handleSubmit shows dueAt error when date is not set", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        await selectOption(user, /unidad tem/i, /pronosticos/i);
        await user.type(screen.getByRole("textbox", { name: /descripci[oó]n/i }), "Escenario");
        await user.type(screen.getByLabelText(/pregunta gu[ií]a/i), "Pregunta");
        fireEvent.change(screen.getByLabelText(/disponibilidad/i), { target: { value: "2025-06-01T00:00" } });
        // dueAt intentionally left empty
        fireEvent.submit(document.querySelector("form")!);

        await waitFor(() => {
            expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
        });
    });

    it("handleSubmit shows suggestedTechniques error in EDA mode when no techniques added", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        await selectOption(user, /unidad tem/i, /pronosticos/i);
        await showTechniquesSection(user); // switch to harvard_with_eda
        await user.type(screen.getByRole("textbox", { name: /descripci[oó]n/i }), "Escenario completo");
        await user.type(screen.getByLabelText(/pregunta gu[ií]a/i), "Pregunta guía");
        fireEvent.change(screen.getByLabelText(/disponibilidad/i), { target: { value: "2025-06-01T00:00" } });
        fireEvent.change(screen.getByLabelText(/fecha de cierre/i), { target: { value: "2025-07-01T00:00" } });
        // No techniques added — bypass disabled button
        fireEvent.submit(document.querySelector("form")!);

        await waitFor(() => {
            expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
        });
    });

    it("topicUnit is not required when the selected module has no units", async () => {
        // Override course detail to return a module with no units
        server.use(
            http.get("/api/teacher/courses/:courseId", () =>
                HttpResponse.json({
                    course: {
                        id: "course-1", title: "Gerencia de Operaciones", code: "GO-101",
                        semester: "2025-1", academic_level: "MBA", status: "active",
                        max_students: 35, students_count: 32, active_cases_count: 1,
                    },
                    syllabus: {
                        department: "Administracion", knowledge_area: "Operaciones",
                        nbc: "Administracion", version_label: "v1", academic_load: "48 horas",
                        course_description: "Curso", general_objective: "Obj",
                        specific_objectives: [], evaluation_strategy: [],
                        didactic_strategy: { methodological_perspective: "Aplicada", pedagogical_modality: "Presencial" },
                        integrative_project: "", bibliography: [], teacher_notes: "",
                        ai_grounding_context: {
                            course_identity: {
                                course_id: "course-1", course_title: "Gerencia de Operaciones",
                                academic_level: "MBA", department: "Administracion",
                                knowledge_area: "Operaciones", nbc: "Administracion",
                            },
                            pedagogical_intent: { general_objective: "Obj", specific_objectives: [] },
                            curriculum_scope: { coverage_signal: "focused" },
                        },
                        modules: [{
                            module_id: "module-1",
                            module_title: "Fundamentos de Operaciones",
                            weeks: "1-4",
                            module_summary: "Base",
                            learning_outcomes: [],
                            units: [], // No units
                            cross_course_connections: "",
                        }],
                    },
                }),
            ),
        );

        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await enableSuggestions(user);
        // No topicUnit selected — unit Select is disabled (no units)
        await user.type(screen.getByRole("textbox", { name: /descripci[oó]n/i }), "Escenario completo");
        await user.type(screen.getByLabelText(/pregunta gu[ií]a/i), "Pregunta guía");
        fireEvent.change(screen.getByLabelText(/disponibilidad/i), { target: { value: "2025-06-01T00:00" } });
        fireEvent.change(screen.getByLabelText(/fecha de cierre/i), { target: { value: "2025-07-01T00:00" } });

        // Button should be enabled even without topicUnit (units.length === 0 → not required)
        await waitFor(() => {
            expect(screen.getByRole("button", { name: /generar caso harvard/i })).not.toBeDisabled();
        });
    });
});

// ─── Task 2 — Profile restriction for harvard_only ───────────────────────────

describe("Task 2 — Profile restriction for harvard_only", () => {
    beforeAll(() => {
        Element.prototype.hasPointerCapture ??= () => false;
        Element.prototype.releasePointerCapture ??= () => {};
        Element.prototype.setPointerCapture ??= () => {};
        Element.prototype.scrollIntoView ??= () => {};
    });

    beforeEach(() => {
        vi.restoreAllMocks();
        sessionStorage.clear();
        server.use(
            http.get("/api/teacher/courses", () =>
                HttpResponse.json({ courses: [], total: 0 }),
            ),
        );
    });

    it("ml_ds option is not shown in the profile dropdown when caseType is harvard_only (default)", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        await user.click(screen.getByLabelText(/perfil del curso/i));
        const options = await screen.findAllByRole("option");
        const labels = options.map((o) => o.textContent ?? "");

        expect(labels.some((l) => /machine learning/i.test(l))).toBe(false);
        expect(labels.some((l) => /negocios/i.test(l))).toBe(true);
    });

    it("switching to harvard_only auto-resets studentProfile from ml_ds to business", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        // Switch to harvard_with_eda to unlock ml_ds option
        await user.click(screen.getByRole("radio", { name: /caso .*an[aá]lisis de datos/i }));

        // Select ml_ds profile
        await user.click(screen.getByLabelText(/perfil del curso/i));
        await user.click(await screen.findByRole("option", { name: /machine learning/i }));

        expect(screen.getByLabelText(/perfil del curso/i)).toHaveTextContent(/machine learning/i);

        // Switch back to harvard_only — should auto-reset profile
        await user.click(screen.getByRole("radio", { name: /solo caso harvard/i }));

        await waitFor(() => {
            expect(screen.getByLabelText(/perfil del curso/i)).toHaveTextContent(/negocios/i);
        });
    });

    it("ml_ds option reappears when switching to harvard_with_eda", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        // Confirm ml_ds is absent by default
        await user.click(screen.getByLabelText(/perfil del curso/i));
        await waitFor(() => {
            const optsBefore = screen.getAllByRole("option");
            expect(optsBefore.some((o) => /machine learning/i.test(o.textContent ?? ""))).toBe(false);
        });

        // Close dropdown
        await user.keyboard("{Escape}");

        // Switch to harvard_with_eda
        await user.click(screen.getByRole("radio", { name: /caso .*an[aá]lisis de datos/i }));

        // ml_ds should now be present
        await user.click(screen.getByLabelText(/perfil del curso/i));
        const optsAfter = await screen.findAllByRole("option");
        expect(optsAfter.some((o) => /machine learning/i.test(o.textContent ?? ""))).toBe(true);
    });
});

// ─── Task 3 — sessionStorage persistence ─────────────────────────────────────

describe("Task 3 — sessionStorage persistence", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
        sessionStorage.clear();
        server.use(
            http.get("/api/teacher/courses", () =>
                HttpResponse.json({ courses: [], total: 0 }),
            ),
        );
    });

    afterEach(() => {
        sessionStorage.clear();
    });

    it("restores form fields from valid sessionStorage data on mount", async () => {
        sessionStorage.setItem(
            FORM_STATE_SESSION_KEY,
            JSON.stringify({
                scenarioDescription: "Escenario restaurado desde storage",
                guidingQuestion: "Pregunta restaurada desde storage",
                subject: "",
                syllabusModule: "",
                topicUnit: "",
                targetGroups: [],
                studentProfile: "business",
                industry: "fintech",
                caseType: "harvard_with_eda",
                notebookToggle: false,
                algorithmMode: "single",
                algorithmPrimary: null,
                algorithmChallenger: null,
                availableFrom: "",
                dueAt: "",
            }),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        expect(await screen.findByDisplayValue("Escenario restaurado desde storage")).toBeInTheDocument();
        expect(screen.getByDisplayValue("Pregunta restaurada desde storage")).toBeInTheDocument();
        expect(screen.getByRole("radio", { name: /caso .*an[aá]lisis de datos/i })).toHaveAttribute("aria-checked", "true");
    });

    it("writes form state to sessionStorage within 1 second of a field change", async () => {
        const user = userEvent.setup();
        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);

        const textarea = screen.getByRole("textbox", { name: /descripci[oó]n/i });
        await user.type(textarea, "Texto guardado en storage");

        await waitFor(
            () => {
                const raw = sessionStorage.getItem(FORM_STATE_SESSION_KEY);
                expect(raw).not.toBeNull();
                const parsed = JSON.parse(raw!);
                expect(parsed.scenarioDescription).toContain("Texto guardado en storage");
            },
            { timeout: 1500 },
        );
    });

    it("removes a corrupted sessionStorage key silently on mount without throwing", () => {
        sessionStorage.setItem(FORM_STATE_SESSION_KEY, "{invalid-json-payload}");

        expect(() => {
            renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        }).not.toThrow();

        expect(sessionStorage.getItem(FORM_STATE_SESSION_KEY)).toBeNull();
    });
});

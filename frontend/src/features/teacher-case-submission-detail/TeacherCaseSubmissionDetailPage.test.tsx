import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";
import { api, ApiError } from "@/shared/api";
import type { TeacherCaseSubmissionDetailResponse } from "@/shared/adam-types";

import { TeacherCaseSubmissionDetailPage } from "./TeacherCaseSubmissionDetailPage";

vi.mock("@/features/teacher-layout/TeacherLayout", () => ({
    TeacherLayout: ({ children, testId }: { children: React.ReactNode; testId?: string }) => (
        <div data-testid={testId ?? "teacher-layout"}>{children}</div>
    ),
}));

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCaseSubmissionDetail: vi.fn(),
            },
        },
    };
});

function createSubmissionDetailResponse(
    overrides?: Partial<TeacherCaseSubmissionDetailResponse>,
): TeacherCaseSubmissionDetailResponse {
    return {
        payload_version: 1,
        case: {
            id: "assignment-1",
            title: "Caso Plataforma",
            deadline: "2026-06-08T15:00:00Z",
            available_from: "2026-06-01T15:00:00Z",
            course_id: "course-1",
            course_code: "A-210",
            course_name: "Analítica Directiva",
            teaching_note: "Prioriza la coherencia entre diagnóstico y recomendación.",
            ...overrides?.case,
        },
        student: {
            membership_id: "membership-1",
            full_name: "Ana Student",
            email: "ana.student@example.edu",
            enrolled_at: "2026-05-20T15:00:00Z",
            ...overrides?.student,
        },
        response_state: {
            status: "submitted",
            first_opened_at: "2026-06-02T12:00:00Z",
            last_autosaved_at: "2026-06-05T18:15:00Z",
            submitted_at: "2026-06-05T19:00:00Z",
            snapshot_id: "snapshot-1",
            snapshot_hash: "hash-123",
            ...overrides?.response_state,
        },
        grade_summary: {
            status: null,
            score: null,
            max_score: 5,
            graded_at: null,
            ...overrides?.grade_summary,
        },
        modules: overrides?.modules ?? [
            {
                id: "M1",
                title: "Módulo 1 · Comprensión del caso",
                questions: [
                    {
                        id: "M1-Q1",
                        order: 1,
                        statement: "Describe la situación principal del caso.",
                        context: "Pregunta 1",
                        expected_solution: "Reconoce el cuello de botella operativo.",
                        student_answer: "La empresa tiene un cuello de botella en onboarding.",
                        student_answer_chars: 58,
                        is_answer_from_draft: false,
                    },
                ],
            },
            {
                id: "M5",
                title: "Módulo 5 · Reflexión",
                questions: [
                    {
                        id: "M5-Q5",
                        order: 1,
                        statement: "Escribe un memo ejecutivo final.",
                        context: "Integra: M1, M2, M3",
                        expected_solution: "Memo estructurado con recomendación y riesgos.",
                        student_answer: "Borrador del memo ejecutivo.",
                        student_answer_chars: 27,
                        is_answer_from_draft: true,
                    },
                ],
            },
        ],
    };
}

function renderPage(initialEntries = ["/teacher/cases/assignment-1/entregas/membership-1"]) {
    return renderWithProviders(
        <Routes>
            <Route path="/teacher/cases/:assignmentId/entregas" element={<div data-testid="submissions-list">Listado</div>} />
            <Route
                path="/teacher/cases/:assignmentId/entregas/:membershipId"
                element={<TeacherCaseSubmissionDetailPage />}
            />
        </Routes>,
        { initialEntries },
    );
}

describe("TeacherCaseSubmissionDetailPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("renders a loading state while the detail query is pending", () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockReturnValue(new Promise(() => undefined));

        renderPage();

        expect(screen.getByText("Cargando detalle de la entrega")).toBeTruthy();
    });

    it("renders the detail payload and switches between modules", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockResolvedValue(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByText("Entrega de Ana Student")).toBeTruthy();
        expect(screen.getByText("Caso Plataforma · A-210 · Analítica Directiva")).toBeTruthy();
        expect(screen.getByText("Describe la situación principal del caso.")).toBeTruthy();
        expect(screen.getByText("Reconoce el cuello de botella operativo.")).toBeTruthy();
        expect(screen.getByText(/Calificación aún en modo lectura/i)).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Abrir módulo M5" }));

        expect(await screen.findByText("Escribe un memo ejecutivo final.")).toBeTruthy();
        expect(screen.getByText("Borrador vigente")).toBeTruthy();
    });

    it("renders an error state and retries the detail query", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail)
            .mockRejectedValueOnce(new ApiError(404, "Not found", "submission_not_found"))
            .mockResolvedValueOnce(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByText("No encontramos esta entrega o no tienes acceso.")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

        expect(await screen.findByText("Entrega de Ana Student")).toBeTruthy();
        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledTimes(2);
    });

    it("refetches the detail payload when the refresh button is pressed", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail)
            .mockResolvedValueOnce(createSubmissionDetailResponse())
            .mockResolvedValueOnce(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByText("Entrega de Ana Student")).toBeTruthy();
        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole("button", { name: /Actualizar entrega/i }));

        await waitFor(() => {
            expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledTimes(2);
        });
    });
});
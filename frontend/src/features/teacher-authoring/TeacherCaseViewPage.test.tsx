import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthContextValue } from "@/app/auth/auth-types";
import { ApiError, api } from "@/shared/api";
import type { TeacherCaseDetailResponse } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

import { TeacherCaseViewPage } from "./TeacherCaseViewPage";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");
    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCaseDetail: vi.fn(),
            },
        },
    };
});

// CasePreview is lazy-loaded; stub it so tests don't need the full module tree
vi.mock("@/features/case-preview/CasePreview", () => ({
    CasePreview: ({ isAlreadyPublished }: { isAlreadyPublished?: boolean }) => (
        <div data-testid="case-preview-stub" data-is-already-published={String(isAlreadyPublished ?? false)}>
            CasePreview
        </div>
    ),
}));

// ── Auth fixture ─────────────────────────────────────────────────────────────

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

// ── Factory ───────────────────────────────────────────────────────────────────

function createCaseDetailResponse(
    overrides?: Partial<TeacherCaseDetailResponse>,
): TeacherCaseDetailResponse {
    return {
        id: "assignment-1",
        title: "Caso de prueba Harvard",
        status: "draft",
        available_from: null,
        deadline: null,
        course_id: "course-1",
        canonical_output: {
            title: "Caso de prueba Harvard",
            subject: "Analítica de Negocios",
            syllabusModule: "Módulo 1",
            guidingQuestion: "¿Cómo optimizar el canal digital?",
            industry: "FinTech",
            academicLevel: "MBA",
            caseType: "harvard_only",
            studentProfile: "business",
            generatedAt: "2026-04-21T00:00:00Z",
            outputDepth: "narrative_only",
            content: {},
        },
        ...overrides,
    };
}

// ── Render helper ─────────────────────────────────────────────────────────────

function renderTeacherCaseViewPage(initialEntry = "/teacher/cases/assignment-1") {
    return renderWithProviders(
        <Routes>
            <Route
                path="/teacher/cases/:assignmentId"
                element={<TeacherCaseViewPage />}
            />
            <Route path="/teacher/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
        </Routes>,
        {
            initialEntries: [initialEntry],
            authValue: teacherAuthValue,
        },
    );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TeacherCaseViewPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("[T1] isLoading — renders skeleton while fetch is in flight", () => {
        // Never resolves during this test
        vi.mocked(api.teacher.getCaseDetail).mockReturnValue(new Promise(() => undefined));

        renderTeacherCaseViewPage();

        expect(screen.getByTestId("teacher-case-view-loading")).toBeTruthy();
        // Skeleton uses animate-pulse — spot-check a structural element exists
        const skeleton = screen.getByTestId("teacher-case-view-loading");
        expect(skeleton.querySelector(".animate-pulse")).toBeTruthy();
    });

    it("[T2] isError 404 — shows 'Caso no encontrado' and back button", async () => {
        vi.mocked(api.teacher.getCaseDetail).mockRejectedValueOnce(
            new ApiError(404, "Not found"),
        );

        renderTeacherCaseViewPage();

        expect(await screen.findByText("Caso no encontrado")).toBeTruthy();
        expect(screen.getByRole("button", { name: /volver al dashboard/i })).toBeTruthy();
        expect(screen.queryByText("Error al cargar el caso")).toBeNull();
    });

    it("[T3] isError non-404 — shows generic error message", async () => {
        vi.mocked(api.teacher.getCaseDetail).mockRejectedValueOnce(
            new ApiError(500, "Internal server error"),
        );

        renderTeacherCaseViewPage();

        expect(await screen.findByText("Error al cargar el caso")).toBeTruthy();
        expect(screen.getByRole("button", { name: /volver al dashboard/i })).toBeTruthy();
        expect(screen.queryByText("Caso no encontrado")).toBeNull();
    });

    it("[T4] canonical_output null — renders empty state without crashing", async () => {
        vi.mocked(api.teacher.getCaseDetail).mockResolvedValueOnce(
            createCaseDetailResponse({ canonical_output: null }),
        );

        renderTeacherCaseViewPage();

        expect(await screen.findByTestId("case-empty-state")).toBeTruthy();
        expect(screen.getByText(/El caso aún no tiene contenido generado/)).toBeTruthy();
        expect(screen.queryByTestId("case-preview-stub")).toBeNull();
    });

    it("[T5] happy path — CasePreview renders with canonical_output", async () => {
        vi.mocked(api.teacher.getCaseDetail).mockResolvedValueOnce(
            createCaseDetailResponse({ status: "draft" }),
        );

        renderTeacherCaseViewPage();

        expect(await screen.findByTestId("case-preview-stub")).toBeTruthy();
        // In draft state isAlreadyPublished should be false
        expect(
            screen.getByTestId("case-preview-stub").getAttribute("data-is-already-published"),
        ).toBe("false");
    });

    it("[T6] happy path published — isAlreadyPublished=true passed to CasePreview", async () => {
        vi.mocked(api.teacher.getCaseDetail).mockResolvedValueOnce(
            createCaseDetailResponse({ status: "published" }),
        );

        renderTeacherCaseViewPage();

        await waitFor(() => {
            expect(screen.getByTestId("case-preview-stub")).toBeTruthy();
        });

        expect(
            screen.getByTestId("case-preview-stub").getAttribute("data-is-already-published"),
        ).toBe("true");
    });
});

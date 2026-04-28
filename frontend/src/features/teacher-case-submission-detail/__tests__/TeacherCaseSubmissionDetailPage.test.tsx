import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";
import { api, ApiError } from "@/shared/api";
import type { TeacherCaseSubmissionDetailResponse } from "@/shared/adam-types";

import { TeacherCaseSubmissionDetailPage } from "../TeacherCaseSubmissionDetailPage";

import { createSubmissionDetailResponse } from "./testData";

const previewSpy = vi.fn();

vi.mock("@/features/teacher-layout/TeacherLayout", () => ({
    TeacherLayout: ({ children, testId }: { children: React.ReactNode; testId?: string }) => (
        <div data-testid={testId ?? "teacher-layout"}>{children}</div>
    ),
}));

vi.mock("@/features/teacher-case-submission-detail/TeacherSubmissionPreview", () => ({
    TeacherSubmissionPreview: (props: {
        detail: TeacherCaseSubmissionDetailResponse;
        isRefreshing: boolean;
        onRefresh: () => void;
    }) => {
        previewSpy(props);

        return (
            <div data-testid="teacher-submission-preview">
                <span>{props.detail.student.full_name}</span>
                <span>{String(props.isRefreshing)}</span>
                <button type="button" onClick={props.onRefresh}>Refresh preview</button>
            </div>
        );
    },
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
        previewSpy.mockReset();
    });

    it("renders a loading state while the detail query is pending", () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockReturnValue(new Promise(() => undefined));

        renderPage();

        expect(screen.getByText("Cargando detalle de la entrega")).toBeTruthy();
    });

    it("renders the preview wrapper when the detail query resolves", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockResolvedValue(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByTestId("teacher-submission-preview")).toBeTruthy();
        expect(screen.getByText("Ana Student")).toBeTruthy();
        expect(previewSpy).toHaveBeenCalled();
    });

    it("shows the outdated-app banner when the payload version is unsupported", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockResolvedValue({
            ...createSubmissionDetailResponse(),
            payload_version: 2,
        } as unknown as TeacherCaseSubmissionDetailResponse);

        renderPage();

        expect(await screen.findByText("Tu versión de la app está desactualizada. Recarga para continuar.")).toBeTruthy();
    });

    it("renders an error state and retries the detail query", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail)
            .mockRejectedValueOnce(new ApiError(404, "Not found", "submission_not_found"))
            .mockResolvedValueOnce(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByText("No encontramos esta entrega o no tienes acceso.")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

        expect(await screen.findByTestId("teacher-submission-preview")).toBeTruthy();
        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledTimes(2);
    });

    it("wires the preview refresh action to the query refetch", async () => {
        vi.mocked(api.teacher.getCaseSubmissionDetail)
            .mockResolvedValueOnce(createSubmissionDetailResponse())
            .mockResolvedValueOnce(createSubmissionDetailResponse());

        renderPage();

        expect(await screen.findByTestId("teacher-submission-preview")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Refresh preview/i }));

        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledTimes(2);
    });
});
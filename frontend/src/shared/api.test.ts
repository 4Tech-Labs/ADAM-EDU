import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { createClientMock, getSessionMock } = vi.hoisted(() => {
    const sessionMock = vi.fn();
    const clientMock = vi.fn(() => ({
        auth: {
            getSession: sessionMock,
        },
    }));

    return {
        createClientMock: clientMock,
        getSessionMock: sessionMock,
    };
});

vi.mock("@supabase/supabase-js", () => ({
    createClient: createClientMock,
}));

import { ApiError, api, createSseParser, formatHttpError, resetApiClientForTests } from "./api";

describe("api auth + stream glue", () => {
    beforeEach(() => {
        resetApiClientForTests();
        getSessionMock.mockReset();
        // Default: no active session. Tests that need a token set this explicitly.
        // Required because jsdom defines `window`, so getSupabaseClient() no longer
        // short-circuits on `typeof window === "undefined"`.
        getSessionMock.mockResolvedValue({ data: { session: null }, error: null });
        createClientMock.mockClear();
        vi.unstubAllEnvs();
        vi.unstubAllGlobals();
        vi.stubGlobal("window", {});
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("attaches a bearer token when a Supabase session exists", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "token-123" } },
            error: null,
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ job_id: "job-1" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.authoring.submitJob({
            assignment_title: "Case",
            subject: "Case",
            academic_level: "MBA",
            industry: "FinTech",
            student_profile: "business",
            case_type: "harvard_only",
            syllabus_module: "M1",
            scenario_description: "Scenario",
            guiding_question: "Question",
            topic_unit: "Unit",
            target_groups: ["A"],
            eda_depth: null,
            include_python_code: false,
            suggested_techniques: ["SWOT"],
            available_from: null,
            due_at: null,
        });

        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer token-123");
    });

    it("parses SSE events across chunk boundaries", () => {
        const events: Array<{ event: string; data: string }> = [];
        const parser = createSseParser((event) => events.push(event));

        parser.push("event: metadata\ndata: {\"status\":\"processing\"}\n\n");
        parser.push("event: result\ndata: {\"title\"");
        parser.push(":\"Case\"}\n\n");
        parser.flush();

        expect(events).toEqual([
            { event: "metadata", data: "{\"status\":\"processing\"}" },
            { event: "result", data: "{\"title\":\"Case\"}" },
        ]);
    });

    it("returns a non-generic auth error for forbidden streams", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ detail: "authoring_forbidden" }), {
                    status: 403,
                    headers: { "Content-Type": "application/json" },
                }),
            ),
        );

        await expect(api.authoring.streamProgress("job-1", () => undefined)).rejects.toMatchObject(
            {
                status: 403,
                message: "Acceso denegado para esta accion.",
            } satisfies Pick<ApiError, "status" | "message">,
        );
    });

    it("maps 401 and 403 away from generic network errors", () => {
        expect(formatHttpError(401, "invalid_token")).toBe(
            "Sesion requerida o expirada. Vuelve a iniciar sesion.",
        );
        expect(formatHttpError(403, "membership_required")).toBe(
            "Tu cuenta no tiene membresia activa para usar esta accion.",
        );
    });

    it("surfaces validation messages from structured FastAPI 422 errors", () => {
        expect(formatHttpError(422, [{
            type: "value_error",
            loc: ["body", "semester"],
            msg: "Value error, semester must use YYYY-I or YYYY-II",
            input: "2026-2",
        }])).toBe("Value error, semester must use YYYY-I or YYYY-II");
    });

    it("serializes admin course filters into the expected query string", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ items: [], page: 1, page_size: 8, total: 0, total_pages: 0 }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.admin.listCourses({
            search: " finanzas ",
            semester: "2026-I",
            status: "active",
            academic_level: "Maestría",
            page: 2,
            page_size: 8,
        });

        expect(fetchMock.mock.calls[0]?.[0]).toBe(
            "/api/admin/courses?search=finanzas&semester=2026-I&status=active&academic_level=Maestr%C3%ADa&page=2&page_size=8",
        );
    });

    it("posts the exact admin course payload without flattening teacher_assignment", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ id: "course-1" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.admin.createCourse({
            title: "Gobierno de Datos",
            code: "DAT-550",
            semester: "2026-II",
            academic_level: "Doctorado",
            max_students: 42,
            status: "active",
            teacher_assignment: {
                kind: "pending_invite",
                invite_id: "invite-123",
            },
        });

        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBe("POST");
        expect(options.body).toBe(
            JSON.stringify({
                title: "Gobierno de Datos",
                code: "DAT-550",
                semester: "2026-II",
                academic_level: "Doctorado",
                max_students: 42,
                status: "active",
                teacher_assignment: {
                    kind: "pending_invite",
                    invite_id: "invite-123",
                },
            }),
        );
    });
});

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

import { ApiError, api, formatHttpError, resetApiClientForTests } from "./api";

async function flushAsyncWork() {
    for (let tick = 0; tick < 10; tick += 1) {
        await Promise.resolve();
    }
}

async function flushAsyncWorkUntil(check: () => boolean, maxTicks = 50) {
    for (let tick = 0; tick < maxTicks; tick += 1) {
        if (check()) {
            return;
        }
        await Promise.resolve();
    }
}

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
        vi.useRealTimers();
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
            course_id: "course-1",
                target_course_ids: ["course-1"],
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

    it("emits metadata and result when snapshot is already completed", async () => {
        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "completed",
                    current_step: "completed",
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        await api.authoring.streamProgress("job-1", (event) => events.push(event));

        expect(events[0]).toEqual({ event: "metadata", data: "{\"status\":\"completed\"}" });
        expect(events[1]).toEqual({ event: "result", data: "{\"canonical_output\":{\"title\":\"Case\"}}" });
    });

    it("emits resumable terminal error when snapshot is already failed_resumable", async () => {
        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                job_id: "job-1",
                status: "failed_resumable",
                current_step: "m4_content_generator",
                error_trace: "timeout",
            }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.authoring.streamProgress("job-1", (event) => events.push(event));

        expect(events[0]).toEqual({ event: "metadata", data: "{\"status\":\"failed_resumable\"}" });
        expect(events).toContainEqual({
            event: "error",
            data: "{\"status\":\"failed_resumable\",\"detail\":\"timeout\"}",
        });
    });

    it("posts retry requests to the authoring retry endpoint", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                job_id: "job-1",
                status: "accepted",
                message: "Authoring retry accepted and dispatched to queue.",
            }), {
                status: 202,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        const response = await api.authoring.retryJob("job-1");

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/authoring/jobs/job-1/retry");
        expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
        expect(response.status).toBe("accepted");
    });

    it("fetches the durable progress snapshot from the authoring progress endpoint", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                job_id: "job-1",
                status: "processing",
                current_step: "m4_content_generator",
                progress_seq: 4,
            }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        const response = await api.authoring.getProgress("job-1");

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/authoring/jobs/job-1/progress");
        expect(response.current_step).toBe("m4_content_generator");
        expect(response.progress_seq).toBe(4);
    });

    it("reconciles terminal state after subscribe when initial snapshot is stale", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");

        const channel = {
            on: vi.fn().mockReturnThis(),
            subscribe: vi.fn((callback: (status: string) => void) => {
                callback("SUBSCRIBED");
                return channel;
            }),
        };
        const removeChannelMock = vi.fn().mockResolvedValue(undefined);

        createClientMock.mockImplementationOnce(() => ({
            auth: {
                getSession: getSessionMock,
            },
            channel: vi.fn(() => channel),
            removeChannel: removeChannelMock,
        }));

        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "completed",
                    current_step: "completed",
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        await api.authoring.streamProgress("job-1", (event) => events.push(event));

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/authoring/jobs/job-1/progress");
        expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/authoring/jobs/job-1/progress");
        expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/authoring/jobs/job-1/result");
        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"processing\"}" });
        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"completed\"}" });
        expect(events[events.length - 1]).toEqual({
            event: "result",
            data: "{\"canonical_output\":{\"title\":\"Case\"}}",
        });
        expect(removeChannelMock).toHaveBeenCalledTimes(1);
    });

    it("reconciles an ultra-fast job that completes before realtime subscribes", async () => {
        vi.useFakeTimers();
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");

        const channel = {
            on: vi.fn().mockReturnThis(),
            subscribe: vi.fn(() => channel),
        };
        const removeChannelMock = vi.fn().mockResolvedValue(undefined);

        createClientMock.mockImplementationOnce(() => ({
            auth: {
                getSession: getSessionMock,
            },
            channel: vi.fn(() => channel),
            removeChannel: removeChannelMock,
        }));

        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-fast",
                    status: "processing",
                    bootstrap_state: "initializing",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-fast",
                    status: "completed",
                    current_step: "completed",
                    progress_seq: 2,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-fast",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Ultra fast case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress("job-fast", (event) => events.push(event));

        await flushAsyncWork();
        await vi.advanceTimersByTimeAsync(2000);
        await streamPromise;

        expect(events).toContainEqual({
            event: "metadata",
            data: "{\"status\":\"processing\",\"bootstrap_state\":\"initializing\"}",
        });
        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"completed\"}" });
        expect(events[events.length - 1]).toEqual({
            event: "result",
            data: "{\"canonical_output\":{\"title\":\"Ultra fast case\"}}",
        });
        expect(removeChannelMock).toHaveBeenCalledTimes(1);
    });

    it("ignores stale post-subscribe snapshots after newer realtime progress", async () => {
        vi.useFakeTimers();
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");

        const channel = {
            on: vi.fn().mockReturnThis(),
            subscribe: vi.fn((handler: (status: string) => void) => {
                handler("SUBSCRIBED");
                queueMicrotask(() => handler("CHANNEL_ERROR"));
                return channel;
            }),
        };
        const removeChannelMock = vi.fn().mockResolvedValue(undefined);

        createClientMock.mockImplementationOnce(() => ({
            auth: {
                getSession: getSessionMock,
            },
            channel: vi.fn(() => channel),
            removeChannel: removeChannelMock,
        }));

        const events: Array<{ event: string; data: string }> = [];
        const controller = new AbortController();

        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "m3_content_generator",
                    progress_seq: 3,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                    progress_seq: 2,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                    progress_seq: 2,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress(
            "job-1",
            (event) => events.push(event),
            controller.signal,
        );

        await flushAsyncWork();
        controller.abort();
        await streamPromise;

        const statuses = events
            .filter((event) => event.event === "metadata")
            .map((event) => (JSON.parse(event.data) as { status: string }).status);
        expect(statuses).toEqual(["processing"]);

        const nodes = events
            .filter((event) => event.event === "message")
            .map((event) => (JSON.parse(event.data) as { node: string }).node);
        expect(nodes).toEqual(["m3_content_generator"]);

        expect(removeChannelMock).toHaveBeenCalledTimes(1);
        expect(vi.getTimerCount()).toBe(0);
    });

    it("reconciles a terminal backend failure after realtime channel error", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");

        const channel = {
            on: vi.fn().mockReturnThis(),
            subscribe: vi.fn((handler: (status: string) => void) => {
                handler("SUBSCRIBED");
                queueMicrotask(() => handler("CHANNEL_ERROR"));
                return channel;
            }),
        };
        const removeChannelMock = vi.fn().mockResolvedValue(undefined);

        createClientMock.mockImplementationOnce(() => ({
            auth: {
                getSession: getSessionMock,
            },
            channel: vi.fn(() => channel),
            removeChannel: removeChannelMock,
        }));

        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_architect",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_architect",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "failed",
                    current_step: "failed",
                    progress_seq: 2,
                    error_trace: "checkpoint unavailable",
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        await api.authoring.streamProgress("job-1", (event) => events.push(event));

        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"failed\"}" });
        expect(events).toContainEqual({
            event: "error",
            data: "{\"status\":\"failed\",\"detail\":\"checkpoint unavailable\"}",
        });
        expect(removeChannelMock).toHaveBeenCalledTimes(1);
    });

    it("rehydrates state when a subscribed channel stays silent and the backend completes", async () => {
        vi.useFakeTimers();
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");

        const channel = {
            on: vi.fn().mockReturnThis(),
            subscribe: vi.fn((handler: (status: string) => void) => {
                handler("SUBSCRIBED");
                return channel;
            }),
        };
        const removeChannelMock = vi.fn().mockResolvedValue(undefined);

        createClientMock.mockImplementationOnce(() => ({
            auth: {
                getSession: getSessionMock,
            },
            channel: vi.fn(() => channel),
            removeChannel: removeChannelMock,
        }));

        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-silent",
                    status: "processing",
                    bootstrap_state: "initializing",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-silent",
                    status: "processing",
                    bootstrap_state: "initializing",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-silent",
                    status: "completed",
                    current_step: "completed",
                    progress_seq: 2,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-silent",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Recovered case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress("job-silent", (event) => events.push(event));

        await flushAsyncWork();
        await vi.advanceTimersByTimeAsync(3000);
        await streamPromise;

        expect(events).toContainEqual({
            event: "metadata",
            data: "{\"status\":\"processing\",\"bootstrap_state\":\"initializing\"}",
        });
        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"completed\"}" });
        expect(events[events.length - 1]).toEqual({
            event: "result",
            data: "{\"canonical_output\":{\"title\":\"Recovered case\"}}",
        });
        expect(removeChannelMock).toHaveBeenCalledTimes(1);
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

    it("falls back to polling when realtime client is unavailable and stops on completed", async () => {
        vi.useFakeTimers();

        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                    progress_seq: 2,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "m4_content_generator",
                    progress_seq: 4,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "completed",
                    current_step: "completed",
                    progress_seq: 5,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress("job-1", (event) => events.push(event));

        await flushAsyncWork();
        await vi.advanceTimersByTimeAsync(3000);
        await streamPromise;

        const nodes = events
            .filter((event) => event.event === "message")
            .map((event) => (JSON.parse(event.data) as { node: string }).node);
        expect(nodes).toEqual(["case_writer", "m4_content_generator"]);
        expect(events).toContainEqual({ event: "metadata", data: "{\"status\":\"completed\"}" });
        expect(events[events.length - 1]).toEqual({
            event: "result",
            data: "{\"canonical_output\":{\"title\":\"Case\"}}",
        });
        expect(vi.getTimerCount()).toBe(0);
    });

    it("ignores non-canonical current_step values while polling fallback stays active", async () => {
        vi.useFakeTimers();

        const controller = new AbortController();
        const events: Array<{ event: string; data: string }> = [];
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({
                job_id: "job-1",
                status: "processing",
                current_step: "unknown_internal_node",
            }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress(
            "job-1",
            (event) => events.push(event),
            controller.signal,
        );

        await flushAsyncWork();
        controller.abort();
        await streamPromise;

        expect(events).toEqual([
            { event: "metadata", data: "{\"status\":\"processing\"}" },
        ]);
        expect(vi.getTimerCount()).toBe(0);
    });

    it("does not overlap HTTP polling requests during realtime fallback", async () => {
        vi.useFakeTimers();

        let resolvePendingPoll: ((value: Response) => void) | undefined;
        const pendingPollResponse = new Promise<Response>((resolve) => {
            resolvePendingPoll = resolve;
        });

        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    status: "processing",
                    current_step: "case_writer",
                    progress_seq: 1,
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockImplementationOnce(() => pendingPollResponse)
            .mockResolvedValueOnce(
                new Response(JSON.stringify({
                    job_id: "job-1",
                    assignment_id: "assignment-1",
                    blueprint: {},
                    canonical_output: { title: "Case" },
                }), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                }),
            );
        vi.stubGlobal("fetch", fetchMock);

        const streamPromise = api.authoring.streamProgress("job-1", () => undefined);

        await flushAsyncWorkUntil(() => fetchMock.mock.calls.length >= 2);
        expect(fetchMock).toHaveBeenCalledTimes(2);

        await vi.advanceTimersByTimeAsync(3000);
        expect(fetchMock).toHaveBeenCalledTimes(3);

        await vi.advanceTimersByTimeAsync(3000);
        expect(fetchMock).toHaveBeenCalledTimes(3);

        resolvePendingPoll?.(
            new Response(JSON.stringify({
                job_id: "job-1",
                status: "completed",
                current_step: "completed",
                progress_seq: 2,
            }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        await flushAsyncWorkUntil(() => fetchMock.mock.calls.length >= 4);
        await streamPromise;

        expect(fetchMock).toHaveBeenCalledTimes(4);
        expect(vi.getTimerCount()).toBe(0);
    });

    it("surfaces retry-after metadata when progress snapshot receives 503 backpressure", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ detail: "db_saturated" }), {
                    status: 503,
                    headers: {
                        "Content-Type": "application/json",
                        "Retry-After": "9",
                    },
                }),
            ),
        );

        await expect(api.authoring.streamProgress("job-1", () => undefined)).rejects.toMatchObject(
            {
                status: 503,
                detail: "db_saturated",
                retryAfterSeconds: 9,
                message: "El sistema esta temporalmente saturado. Intenta de nuevo en unos segundos.",
            } satisfies Pick<ApiError, "status" | "detail" | "retryAfterSeconds" | "message">,
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

    it("maps teacher-specific context and provisioning errors to actionable messages", () => {
        expect(formatHttpError(409, "teacher_membership_context_required")).toBe(
            "Tu cuenta tiene multiples membresias docentes activas y requiere seleccion de contexto.",
        );
        expect(formatHttpError(500, "legacy_bridge_missing")).toBe(
            "Tu cuenta docente no esta completamente aprovisionada para consultar casos.",
        );
    });

    it("maps db resilience detail codes to explicit 503 UX copy", () => {
        expect(formatHttpError(503, "db_saturated")).toBe(
            "El sistema esta temporalmente saturado. Intenta de nuevo en unos segundos.",
        );
        expect(formatHttpError(503, "db_timeout")).toBe(
            "La base de datos tardo demasiado en responder. Intenta de nuevo.",
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

    it("requests teacher courses from the shared teacher endpoint with bearer auth", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ courses: [], total: 0 }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.teacher.getCourses();

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/teacher/courses");
        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBeUndefined();
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer teacher-token");
    });

    it("requests teacher cases from the shared teacher endpoint with bearer auth", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ cases: [], total: 0 }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.teacher.getCases();

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/teacher/cases");
        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBeUndefined();
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer teacher-token");
    });

    it("fetches teacher case detail with bearer auth", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const detail = {
            id: "case-1", title: "Test Case", status: "draft",
            available_from: null, deadline: null, course_id: null, canonical_output: null,
        };
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(detail), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.teacher.getCaseDetail("case-1");

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/teacher/cases/case-1");
        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBeUndefined();
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer teacher-token");
    });

    it("publishes a teacher case with PATCH and bearer auth", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const detail = {
            id: "case-1", title: "Test Case", status: "published",
            available_from: null, deadline: null, course_id: null, canonical_output: null,
        };
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(detail), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.teacher.publishCase("case-1");

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/teacher/cases/case-1/publish");
        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBe("PATCH");
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer teacher-token");
    });

    it("updates deadline with PATCH, JSON body, and bearer auth", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const deadline = "2026-06-01T00:00:00Z";
        const detail = {
            id: "case-1", title: "Test Case", status: "draft",
            available_from: null, deadline, course_id: null, canonical_output: null,
        };
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(detail), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await api.teacher.updateDeadline("case-1", { deadline });

        expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/teacher/cases/case-1/deadline");
        const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
        expect(options.method).toBe("PATCH");
        expect(new Headers(options.headers).get("Content-Type")).toBe("application/json");
        expect(new Headers(options.headers).get("Authorization")).toBe("Bearer teacher-token");
        expect(options.body).toBe(JSON.stringify({ deadline }));
    });

    it("rejects publishCase with ApiError on 409 already_published", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ detail: "already_published" }), {
                status: 409,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await expect(api.teacher.publishCase("case-1")).rejects.toMatchObject({
            status: 409,
        });
    });

    it("rejects updateDeadline with ApiError on 422 deadline_before_available_from", async () => {
        vi.stubEnv("VITE_SUPABASE_URL", "https://example.supabase.co");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key");
        getSessionMock.mockResolvedValue({
            data: { session: { access_token: "teacher-token" } },
            error: null,
        });

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify({ detail: "deadline_before_available_from" }), {
                status: 422,
                headers: { "Content-Type": "application/json" },
            }),
        );
        vi.stubGlobal("fetch", fetchMock);

        await expect(
            api.teacher.updateDeadline("case-1", {
                available_from: "2026-06-10T00:00:00Z",
                deadline: "2026-06-01T00:00:00Z",
            }),
        ).rejects.toMatchObject({ status: 422 });
    });
});

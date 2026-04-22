import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, ProgressTransportDegradedError } from "@/shared/api";
import {
    AUTHORING_PROGRESS_STEP_IDS,
    type AuthoringBootstrapState,
    type AuthoringProgressStep,
    type AuthoringJobCreateRequest,
    type AuthoringJobStatusResponse,
    type AuthoringJobResultResponse,
    type CanonicalCaseOutput,
    type CaseFormData,
} from "@/shared/adam-types";

const ACTIVE_AUTHORING_JOB_STORAGE_KEY = "adam_authoring_active_job";
const STALE_RECOVERY_MESSAGE = "La sesion de recuperacion ya no esta disponible. Vuelve al formulario para iniciar una nueva generacion.";

type ProgressScope = "narrative" | "technical";

const AUTHORING_PROGRESS_STEP_SET = new Set<string>(AUTHORING_PROGRESS_STEP_IDS);

interface PersistedActiveAuthoringJob {
    jobId: string;
    scope: ProgressScope;
}

function isProgressScope(value: unknown): value is ProgressScope {
    return value === "narrative" || value === "technical";
}

function persistActiveAuthoringJob(state: PersistedActiveAuthoringJob): void {
    if (typeof window === "undefined") {
        return;
    }
    sessionStorage.setItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY, JSON.stringify(state));
}

function clearPersistedActiveAuthoringJob(): void {
    if (typeof window === "undefined") {
        return;
    }
    sessionStorage.removeItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY);
}

function readPersistedActiveAuthoringJob(): PersistedActiveAuthoringJob | null {
    if (typeof window === "undefined") {
        return null;
    }

    const raw = sessionStorage.getItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY);
    if (!raw) {
        return null;
    }

    try {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        if (typeof parsed.jobId !== "string" || parsed.jobId.trim() === "") {
            clearPersistedActiveAuthoringJob();
            return null;
        }
        if (!isProgressScope(parsed.scope)) {
            clearPersistedActiveAuthoringJob();
            return null;
        }

        return { jobId: parsed.jobId, scope: parsed.scope };
    } catch {
        clearPersistedActiveAuthoringJob();
        return null;
    }
}

function parseEventPayload(data: string) {
    return JSON.parse(data) as Record<string, unknown>;
}

function isAuthoringJobStatus(value: unknown): value is AuthoringJobStatusResponse["status"] {
    return (
        value === "pending"
        || value === "processing"
        || value === "completed"
        || value === "failed"
        || value === "failed_resumable"
    );
}

function isAuthoringProgressStep(value: unknown): value is AuthoringProgressStep {
    return typeof value === "string" && AUTHORING_PROGRESS_STEP_SET.has(value);
}

function isAuthoringBootstrapState(value: unknown): value is AuthoringBootstrapState {
    return value === "initializing";
}

function getProgressStreamErrorMessage(error: unknown) {
    if (error instanceof ApiError) {
        if (error.status === 503 && error.retryAfterSeconds) {
            return `${error.message} Reintenta en ${error.retryAfterSeconds}s.`;
        }
        return error.message;
    }

    return "No se pudo conectar al canal de progreso en tiempo real.";
}

function getTerminalErrorMessage(status: AuthoringJobStatusResponse["status"], detail?: unknown) {
    if (typeof detail === "string" && detail.trim() !== "") {
        return detail;
    }

    if (status === "failed_resumable") {
        return "La generacion se interrumpio por un error transitorio. Puedes reintentar sin perder el progreso ya completado.";
    }

    return "Error del servidor durante la generacion.";
}

function toCanonicalCaseOutput(response: AuthoringJobResultResponse): CanonicalCaseOutput {
    if (response.canonical_output && typeof response.canonical_output === "object") {
        return response.canonical_output as CanonicalCaseOutput;
    }

    return response as unknown as CanonicalCaseOutput;
}

export function buildAuthoringJobCreateRequest(formData: CaseFormData): AuthoringJobCreateRequest {
    return {
        assignment_title: formData.subject || "Untitled Case",
        course_id: formData.courseId,
        target_course_ids: formData.targetCourseIds,
        subject: formData.subject,
        academic_level: formData.academicLevel,
        industry: formData.industry,
        student_profile: formData.studentProfile,
        case_type: formData.caseType,
        syllabus_module: formData.syllabusModule,
        scenario_description: formData.scenarioDescription,
        guiding_question: formData.guidingQuestion,
        topic_unit: formData.topicUnit,
        target_groups: formData.targetGroups,
        eda_depth: formData.edaDepth ?? null,
        include_python_code: formData.includePythonCode,
        suggested_techniques: formData.suggestedTechniques,
        available_from: formData.availableFrom || null,
        due_at: formData.dueAt || null,
    };
}

export function useAuthoringJobProgress() {
    const [jobId, setJobId] = useState<string | null>(null);
    const [status, setStatus] = useState<AuthoringJobStatusResponse["status"] | null>(null);
    const [activeAgent, setActiveAgent] = useState<AuthoringProgressStep | undefined>(undefined);
    const [errorTrace, setErrorTrace] = useState<string | null>(null);
    const [result, setResult] = useState<CanonicalCaseOutput | null>(null);
    const [isStreaming, setIsStreaming] = useState(false);
    const [progressScope, setProgressScope] = useState<ProgressScope | null>(null);
    const [bootstrapState, setBootstrapState] = useState<AuthoringBootstrapState | undefined>(undefined);

    const streamAbortRef = useRef<AbortController | null>(null);
    const bootstrapResumedJobRef = useRef<
        ((id: string, scope: ProgressScope, opts: { persist?: boolean; recoveryAttempt?: number }) => Promise<void>)
        | null
    >(null);

    const reset = useCallback(() => {
        streamAbortRef.current?.abort();
        streamAbortRef.current = null;
        setJobId(null);
        setStatus(null);
        setActiveAgent(undefined);
        setErrorTrace(null);
        setResult(null);
        setIsStreaming(false);
        setProgressScope(null);
        setBootstrapState(undefined);
        clearPersistedActiveAuthoringJob();
    }, []);

    const startStreaming = useCallback((
        id: string,
        scope: ProgressScope,
        opts?: {
            persist?: boolean;
            preserveActiveAgent?: boolean;
            preserveActiveBootstrapState?: boolean;
            recoveryAttempt?: number;
        },
    ) => {
        streamAbortRef.current?.abort();

        const controller = new AbortController();
        streamAbortRef.current = controller;

        setJobId(id);
        setProgressScope(scope);
        setIsStreaming(true);
        setErrorTrace(null);
        setResult(null);
        if (!opts?.preserveActiveAgent) {
            setActiveAgent(undefined);
        }
        if (!opts?.preserveActiveBootstrapState) {
            setBootstrapState(undefined);
        }

        if (opts?.persist !== false) {
            persistActiveAuthoringJob({ jobId: id, scope });
        }

        void api.authoring
            .streamProgress(
                id,
                ({ event, data }) => {
                    try {
                        const payload = parseEventPayload(data);

                        if (event === "metadata") {
                            const nextStatus = payload.status;
                            if (isAuthoringJobStatus(nextStatus)) {
                                setStatus(nextStatus);
                            }
                            const nextBootstrapState = payload.bootstrap_state;
                            setBootstrapState(
                                isAuthoringBootstrapState(nextBootstrapState)
                                    ? nextBootstrapState
                                    : undefined,
                            );
                            return;
                        }

                        if (event === "message") {
                            const node = payload.node;
                            if (typeof node === "string") {
                                setActiveAgent(node as AuthoringProgressStep);
                                setBootstrapState(undefined);
                            }
                            return;
                        }

                        if (event === "result") {
                            if (payload.canonical_output && typeof payload.canonical_output === "object") {
                                setResult(payload.canonical_output as CanonicalCaseOutput);
                            } else if (payload.result && typeof payload.result === "object") {
                                setResult(payload.result as CanonicalCaseOutput);
                            } else {
                                setResult(payload as unknown as CanonicalCaseOutput);
                            }

                            setStatus("completed");
                            setIsStreaming(false);
                            setBootstrapState(undefined);
                            clearPersistedActiveAuthoringJob();
                            controller.abort();
                            return;
                        }

                        if (event === "error") {
                            const payloadStatus = payload.status;
                            const nextStatus = isAuthoringJobStatus(payloadStatus)
                                ? payloadStatus
                                : "failed";
                            const detail = payload.detail;
                            setErrorTrace(
                                typeof detail === "string"
                                    ? detail
                                    : "Error del servidor durante la generacion.",
                            );
                            setStatus(nextStatus);
                            setIsStreaming(false);
                            setBootstrapState(undefined);
                            if (nextStatus !== "failed_resumable") {
                                clearPersistedActiveAuthoringJob();
                            }
                            controller.abort();
                        }
                    } catch {
                        setErrorTrace("Respuesta invalida del canal de progreso en tiempo real.");
                        setStatus("failed");
                        setIsStreaming(false);
                        clearPersistedActiveAuthoringJob();
                        controller.abort();
                    }
                },
                controller.signal,
            )
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }

                if (error instanceof ProgressTransportDegradedError && (opts?.recoveryAttempt ?? 0) < 1) {
                    void bootstrapResumedJobRef.current?.(id, scope, {
                        persist: opts?.persist,
                        recoveryAttempt: (opts?.recoveryAttempt ?? 0) + 1,
                    });
                    return;
                }

                setErrorTrace(getProgressStreamErrorMessage(error));
                setStatus("failed");
                setIsStreaming(false);
                setBootstrapState(undefined);
                clearPersistedActiveAuthoringJob();
            })
            .finally(() => {
                if (streamAbortRef.current === controller) {
                    streamAbortRef.current = null;
                }
            });
    }, []);

    const bootstrapResumedJob = useCallback(
        async (
            id: string,
            scope: ProgressScope,
            opts: { persist?: boolean; recoveryAttempt?: number },
        ) => {
            setJobId(id);
            setProgressScope(scope);
            setResult(null);
            setErrorTrace(null);

            try {
                const snapshot = await api.authoring.getProgress(id);
                const checkpointStep = isAuthoringProgressStep(snapshot.current_step)
                    ? snapshot.current_step
                    : undefined;
                const nextBootstrapState = isAuthoringBootstrapState(snapshot.bootstrap_state)
                    ? snapshot.bootstrap_state
                    : undefined;

                if (snapshot.status === "completed") {
                    const resultResponse = await api.authoring.getResult(id);
                    setResult(toCanonicalCaseOutput(resultResponse));
                    setStatus("completed");
                    setIsStreaming(false);
                    setBootstrapState(undefined);
                    clearPersistedActiveAuthoringJob();
                    return;
                }

                if (snapshot.status === "failed" || snapshot.status === "failed_resumable") {
                    setStatus(snapshot.status);
                    setErrorTrace(getTerminalErrorMessage(snapshot.status, snapshot.error_trace));
                    setIsStreaming(false);
                    setBootstrapState(undefined);
                    if (snapshot.status !== "failed_resumable") {
                        clearPersistedActiveAuthoringJob();
                    }
                    return;
                }

                setStatus(snapshot.status);
                setBootstrapState(nextBootstrapState);
                if (checkpointStep) {
                    setActiveAgent(checkpointStep);
                }

                startStreaming(id, scope, {
                    persist: opts.persist,
                    preserveActiveAgent: true,
                    preserveActiveBootstrapState: true,
                    recoveryAttempt: opts.recoveryAttempt,
                });
            } catch (error) {
                if (error instanceof ApiError && error.status === 404) {
                    clearPersistedActiveAuthoringJob();
                    setJobId(null);
                    setProgressScope(null);
                    setActiveAgent(undefined);
                    setBootstrapState(undefined);
                    setErrorTrace(STALE_RECOVERY_MESSAGE);
                    setStatus("failed");
                    setIsStreaming(false);
                    return;
                }

                setErrorTrace(getProgressStreamErrorMessage(error));
                setStatus("failed");
                setIsStreaming(false);
                setBootstrapState(undefined);
            }
        },
        [startStreaming],
    );

    bootstrapResumedJobRef.current = bootstrapResumedJob;

    useEffect(() => {
        const persisted = readPersistedActiveAuthoringJob();
        if (!persisted) {
            return;
        }

        void bootstrapResumedJob(persisted.jobId, persisted.scope, { persist: false });
    }, [bootstrapResumedJob]);

    const submitJob = useCallback(
        async (formData: CaseFormData) => {
            try {
                reset();
                setStatus("pending");

                const data = await api.authoring.submitJob(buildAuthoringJobCreateRequest(formData));
                if (data.job_id) {
                    const scope: ProgressScope = formData.caseType === "harvard_only" ? "narrative" : "technical";
                    startStreaming(data.job_id, scope);
                    return;
                }

                setErrorTrace("No job_id returned from server.");
                setStatus("failed");
            } catch (error) {
                setErrorTrace(error instanceof Error ? error.message : "Error de red");
                setStatus("failed");
            }
        },
        [reset, startStreaming],
    );

    const retryJob = useCallback(async () => {
        const retryTargetJobId = jobId;
        if (!retryTargetJobId) {
            setErrorTrace("No se encontro un job para reintentar.");
            setStatus("failed");
            return;
        }

        const persisted = readPersistedActiveAuthoringJob();
        const scope = progressScope ?? persisted?.scope;
        if (!scope) {
            setErrorTrace("No se pudo recuperar el contexto del progreso para reintentar.");
            setStatus("failed");
            return;
        }

        try {
            setErrorTrace(null);
            setStatus("pending");
            const retryResponse = await api.authoring.retryJob(retryTargetJobId);
            if (!retryResponse.job_id || typeof retryResponse.job_id !== "string") {
                throw new Error("El servidor devolvio una respuesta de reintento invalida.");
            }
            await bootstrapResumedJob(retryResponse.job_id, scope, { persist: true });
        } catch (error) {
            setErrorTrace(error instanceof Error ? error.message : "Error de red");
            setStatus("failed");
        }
    }, [bootstrapResumedJob, jobId, progressScope]);

    return {
        jobId,
        status,
        errorTrace,
        result,
        activeAgent,
        submitJob,
        retryJob,
        reset,
        isStreaming,
        progressScope,
        bootstrapState,
    };
}

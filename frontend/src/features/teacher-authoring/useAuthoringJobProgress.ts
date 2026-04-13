import { useCallback, useRef, useState } from "react";

import { ApiError, api } from "@/shared/api";
import {
    type AuthoringJobCreateRequest,
    type AuthoringJobStatusResponse,
    type CanonicalCaseOutput,
    type CaseFormData,
} from "@/shared/adam-types";

function parseEventPayload(data: string) {
    return JSON.parse(data) as Record<string, unknown>;
}

function getProgressStreamErrorMessage(error: unknown) {
    if (error instanceof ApiError) {
        return error.message;
    }

    return "No se pudo conectar al canal de progreso en tiempo real.";
}

export function buildAuthoringJobCreateRequest(formData: CaseFormData): AuthoringJobCreateRequest {
    return {
        assignment_title: formData.subject || "Untitled Case",
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
    const [activeAgent, setActiveAgent] = useState<string | undefined>(undefined);
    const [errorTrace, setErrorTrace] = useState<string | null>(null);
    const [result, setResult] = useState<CanonicalCaseOutput | null>(null);
    const [isStreaming, setIsStreaming] = useState(false);

    const streamAbortRef = useRef<AbortController | null>(null);

    const reset = useCallback(() => {
        streamAbortRef.current?.abort();
        streamAbortRef.current = null;
        setJobId(null);
        setStatus(null);
        setActiveAgent(undefined);
        setErrorTrace(null);
        setResult(null);
        setIsStreaming(false);
    }, []);

    const startStreaming = useCallback((id: string) => {
        streamAbortRef.current?.abort();

        const controller = new AbortController();
        streamAbortRef.current = controller;

        setJobId(id);
        setIsStreaming(true);
        setStatus("processing");
        setErrorTrace(null);

        void api.authoring
            .streamProgress(
                id,
                ({ event, data }) => {
                    try {
                        const payload = parseEventPayload(data);

                        if (event === "metadata") {
                            const nextStatus = payload.status;
                            if (typeof nextStatus === "string") {
                                setStatus(nextStatus as AuthoringJobStatusResponse["status"]);
                            }
                            return;
                        }

                        if (event === "message") {
                            const node = payload.node;
                            if (typeof node === "string") {
                                setActiveAgent(node);
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
                            controller.abort();
                            return;
                        }

                        if (event === "error") {
                            const detail = payload.detail;
                            setErrorTrace(
                                typeof detail === "string"
                                    ? detail
                                    : "Error del servidor durante la generacion.",
                            );
                            setStatus("failed");
                            setIsStreaming(false);
                            controller.abort();
                        }
                    } catch {
                        setErrorTrace("Respuesta invalida del stream de progreso.");
                        setStatus("failed");
                        setIsStreaming(false);
                        controller.abort();
                    }
                },
                controller.signal,
            )
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }

                setErrorTrace(getProgressStreamErrorMessage(error));
                setStatus("failed");
                setIsStreaming(false);
            })
            .finally(() => {
                if (streamAbortRef.current === controller) {
                    streamAbortRef.current = null;
                }
            });
    }, []);

    const submitJob = useCallback(
        async (formData: CaseFormData) => {
            try {
                reset();
                setStatus("pending");

                const data = await api.authoring.submitJob(buildAuthoringJobCreateRequest(formData));
                if (data.job_id) {
                    startStreaming(data.job_id);
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

    return { jobId, status, errorTrace, result, activeAgent, submitJob, reset, isStreaming };
}

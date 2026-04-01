import { useState, useRef, useCallback } from "react";
import { api } from "@/shared/api";
import { type CanonicalCaseOutput, type CaseFormData, type AuthoringJobStatusResponse } from "@/shared/adam-types";

export function useAuthoringJobProgress() {
    const [jobId, setJobId] = useState<string | null>(null);
    const [status, setStatus] = useState<AuthoringJobStatusResponse["status"] | null>(null);
    const [activeAgent, setActiveAgent] = useState<string | undefined>(undefined);
    const [errorTrace, setErrorTrace] = useState<string | null>(null);
    const [result, setResult] = useState<CanonicalCaseOutput | null>(null);
    const [isStreaming, setIsStreaming] = useState(false);

    const eventSourceRef = useRef<EventSource | null>(null);

    const reset = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
        setJobId(null);
        setStatus(null);
        setActiveAgent(undefined);
        setErrorTrace(null);
        setResult(null);
        setIsStreaming(false);
    }, []);

    const startStreaming = useCallback((id: string) => {
        reset();
        setJobId(id);
        setIsStreaming(true);
        setStatus("processing"); // Immediately set to processing since we have a job ID

        const url = api.authoring.getProgressUrl(id);
        const sse = new EventSource(url);
        eventSourceRef.current = sse;

        sse.addEventListener("metadata", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                if (data.status) setStatus(data.status);
            } catch (err) {
                console.error("Error parsing metadata:", err);
            }
        });

        sse.addEventListener("message", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                if (data.node) {
                    setActiveAgent(data.node);
                }
            } catch (err) {
                console.error("Error parsing message:", err);
            }
        });

        sse.addEventListener("result", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                if (data.canonical_output) {
                    setResult(data.canonical_output);
                } else if (data.result) {
                    setResult(data.result);
                } else {
                    setResult(data);
                }
                setStatus("completed");
                setIsStreaming(false);
                sse.close();
            } catch (err) {
                console.error("Error parsing result:", err);
            }
        });

        sse.addEventListener("error", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                if (data.detail) {
                    setErrorTrace(data.detail);
                }
            } catch {
                if (sse.readyState === EventSource.CLOSED) {
                    // Normal closure but without 'result' event. Wait, maybe the API closes it.
                } else {
                    setErrorTrace("Network error connecting to SSE stream.");
                }
            }
            setStatus("failed");
            setIsStreaming(false);
            sse.close();
        });

    }, [reset]);

    const submitJob = useCallback(async (formData: CaseFormData) => {
        try {
            reset();
            setStatus("pending");
            
            const reqBody = {
                teacher_id: "teacher-123",
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

            const data = await api.authoring.submitJob(reqBody);
            if (data.job_id) {
                startStreaming(data.job_id);
            } else {
                setErrorTrace("No job_id returned from server.");
                setStatus("failed");
            }
        } catch (err) {
            setErrorTrace(err instanceof Error ? err.message : "Error network");
            setStatus("failed");
        }
    }, [startStreaming, reset]);

    return { jobId, status, errorTrace, result, activeAgent, submitJob, reset, isStreaming };
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
    StudentCaseDetailResponse,
    StudentCaseDraftRequest,
    StudentCasesResponse,
    StudentCoursesResponse,
    StudentCaseSubmitRequest,
} from "@/shared/adam-types";
import { ApiError, api, getApiErrorCode, getApiErrorMessage } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

const DETAIL_STALE_TIME_MS = 30_000;
export const AUTOSAVE_DELAY_MS = 1_500;
const AUTOSAVE_RETRY_DELAYS_MS = [1_000, 2_000, 4_000] as const;
const DRAFT_STORAGE_PREFIX = "student-draft:";

export type StudentAutosaveState = "idle" | "dirty" | "saving" | "retrying" | "saved" | "error";

export interface StudentRuntimeBannerState {
    tone: "amber" | "red" | "emerald";
    title: string;
    message: string;
}

interface StudentDraftBackup {
    answers: Record<string, string>;
    version: number;
    ts: number;
}

function serializeAnswers(answers: Record<string, string>): string {
    return JSON.stringify(answers);
}

function buildDraftStorageKey(assignmentId: string): string {
    return `${DRAFT_STORAGE_PREFIX}${assignmentId}`;
}

function readDraftBackup(assignmentId: string): StudentDraftBackup | null {
    if (!assignmentId || typeof window === "undefined") {
        return null;
    }

    try {
        const raw = window.localStorage.getItem(buildDraftStorageKey(assignmentId));
        if (!raw) {
            return null;
        }

        const parsed = JSON.parse(raw) as Partial<StudentDraftBackup>;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            return null;
        }

        if (typeof parsed.version !== "number" || typeof parsed.ts !== "number") {
            return null;
        }

        if (!parsed.answers || typeof parsed.answers !== "object" || Array.isArray(parsed.answers)) {
            return null;
        }

        const answers = Object.entries(parsed.answers).reduce<Record<string, string>>((accumulator, [key, value]) => {
            if (typeof value === "string") {
                accumulator[key] = value;
            }
            return accumulator;
        }, {});

        return {
            answers,
            version: parsed.version,
            ts: parsed.ts,
        };
    } catch {
        return null;
    }
}

function writeDraftBackup(assignmentId: string, backup: StudentDraftBackup) {
    if (!assignmentId || typeof window === "undefined") {
        return;
    }

    window.localStorage.setItem(buildDraftStorageKey(assignmentId), JSON.stringify(backup));
}

function clearDraftBackup(assignmentId: string) {
    if (!assignmentId || typeof window === "undefined") {
        return;
    }

    window.localStorage.removeItem(buildDraftStorageKey(assignmentId));
}

function isReadOnlyDetail(detail: StudentCaseDetailResponse | undefined): boolean {
    if (!detail) {
        return false;
    }

    return (
        detail.assignment.status === "submitted"
        || detail.assignment.status === "closed"
        || detail.response.status === "submitted"
    );
}

function isRetriableDraftError(error: unknown): boolean {
    if (error instanceof ApiError) {
        return error.status >= 500;
    }

    return error instanceof TypeError;
}

function waitForDelay(milliseconds: number): Promise<void> {
    return new Promise((resolve) => {
        window.setTimeout(resolve, milliseconds);
    });
}

function isPendingDashboardStatus(status: StudentCasesResponse["cases"][number]["status"]): boolean {
    return status === "available" || status === "in_progress" || status === "upcoming";
}

function updateDashboardCachesAfterSubmit(
    queryClient: ReturnType<typeof useQueryClient>,
    assignmentId: string,
) {
    let nextCases: StudentCasesResponse["cases"] | null = null;

    queryClient.setQueryData(
        queryKeys.student.cases(),
        (current: StudentCasesResponse | undefined) => {
            if (!current) {
                return current;
            }

            nextCases = current.cases.map((caseItem) => (
                caseItem.id === assignmentId
                    ? { ...caseItem, status: "submitted" }
                    : caseItem
            ));

            return {
                ...current,
                cases: nextCases,
            };
        },
    );

    if (!nextCases) {
        return;
    }

    queryClient.setQueryData(
        queryKeys.student.courses(),
        (current: StudentCoursesResponse | undefined) => {
            if (!current) {
                return current;
            }

            return {
                ...current,
                courses: current.courses.map((course) => {
                    let pendingCasesCount = 0;
                    let nextCaseTitle: string | null = null;
                    let nextDeadline: string | null = null;

                    for (const caseItem of nextCases ?? []) {
                        if (!caseItem.course_codes.includes(course.code) || !isPendingDashboardStatus(caseItem.status)) {
                            continue;
                        }

                        pendingCasesCount += 1;

                        if (nextCaseTitle === null) {
                            nextCaseTitle = caseItem.title;
                            nextDeadline = caseItem.deadline;
                            continue;
                        }

                        if (
                            nextDeadline
                            && caseItem.deadline
                            && Date.parse(caseItem.deadline) < Date.parse(nextDeadline)
                        ) {
                            nextCaseTitle = caseItem.title;
                            nextDeadline = caseItem.deadline;
                        }
                    }

                    return {
                        ...course,
                        pending_cases_count: pendingCasesCount,
                        next_case_title: nextCaseTitle,
                        next_deadline: nextDeadline,
                    };
                }),
            };
        },
    );
}

export function useStudentCaseResolution(assignmentId: string) {
    const queryClient = useQueryClient();

    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [version, setVersion] = useState(0);
    const [lastAutosavedAt, setLastAutosavedAt] = useState<string | null>(null);
    const [submittedAt, setSubmittedAt] = useState<string | null>(null);
    const [autosaveState, setAutosaveState] = useState<StudentAutosaveState>("idle");
    const [isDirty, setIsDirty] = useState(false);
    const [errorBanner, setErrorBanner] = useState<StudentRuntimeBannerState | null>(null);
    const [readOnlyOverride, setReadOnlyOverride] = useState(false);
    const [isConflictModalOpen, setIsConflictModalOpen] = useState(false);
    const [isReloadingConflict, setIsReloadingConflict] = useState(false);
    const [isDeadlineModalOpen, setIsDeadlineModalOpen] = useState(false);

    const assignmentIdRef = useRef(assignmentId);
    const answersRef = useRef(answers);
    const versionRef = useRef(version);
    const dirtyRef = useRef(isDirty);
    const detailRef = useRef<StudentCaseDetailResponse | undefined>(undefined);
    const readOnlyRef = useRef(false);
    const pendingTimerRef = useRef<number | null>(null);
    const saveInFlightRef = useRef(false);
    const queuedFlushRef = useRef(false);
    const immediateAutosaveRef = useRef(false);
    const hydratedAssignmentIdRef = useRef<string | null>(null);
    const unmountedRef = useRef(false);

    assignmentIdRef.current = assignmentId;
    answersRef.current = answers;
    versionRef.current = version;
    dirtyRef.current = isDirty;

    const detailQuery = useQuery({
        queryKey: queryKeys.student.caseDetail(assignmentId),
        queryFn: () => api.student.getCaseDetail(assignmentId),
        enabled: Boolean(assignmentId),
        staleTime: DETAIL_STALE_TIME_MS,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
    });

    const detail = detailQuery.data;
    const effectiveStatus = detail?.assignment.status ?? "available";
    const isReadOnly = readOnlyOverride || isReadOnlyDetail(detail);
    const hasAnyAnswer = useMemo(
        () => Object.values(answers).some((value) => value.trim().length > 0),
        [answers],
    );

    detailRef.current = detail;
    readOnlyRef.current = isReadOnly;

    const saveDraftMutation = useMutation({
        mutationFn: (request: StudentCaseDraftRequest) => api.student.saveCaseDraft(assignmentId, request),
        onSuccess: (response, request) => {
            queryClient.setQueryData(
                queryKeys.student.caseDetail(assignmentId),
                (current: StudentCaseDetailResponse | undefined) => {
                    if (!current) {
                        return current;
                    }

                    return {
                        ...current,
                        assignment: {
                            ...current.assignment,
                            status: current.assignment.status === "available" ? "in_progress" : current.assignment.status,
                        },
                        response: {
                            ...current.response,
                            answers: request.answers,
                            version: response.version,
                            last_autosaved_at: response.last_autosaved_at,
                            status: current.response.status === "submitted" ? "submitted" : "draft",
                        },
                    };
                },
            );

            void queryClient.invalidateQueries({ queryKey: queryKeys.student.cases() });
        },
    });

    const submitMutation = useMutation({
        mutationFn: (request: StudentCaseSubmitRequest) => api.student.submitCase(assignmentId, request),
        onSuccess: (response, request) => {
            queryClient.setQueryData(
                queryKeys.student.caseDetail(assignmentId),
                (current: StudentCaseDetailResponse | undefined) => {
                    if (!current) {
                        return current;
                    }

                    return {
                        ...current,
                        assignment: {
                            ...current.assignment,
                            status: "submitted",
                        },
                        response: {
                            ...current.response,
                            answers: request.answers,
                            version: response.version,
                            status: "submitted",
                            submitted_at: response.submitted_at,
                        },
                    };
                },
            );

            updateDashboardCachesAfterSubmit(queryClient, assignmentId);

            void queryClient.invalidateQueries({ queryKey: queryKeys.student.caseDetail(assignmentId) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.student.cases() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.student.courses() });
        },
    });

    const clearPendingAutosaveTimer = useCallback(() => {
        if (pendingTimerRef.current !== null) {
            window.clearTimeout(pendingTimerRef.current);
            pendingTimerRef.current = null;
        }
    }, []);

    const saveDraftWithRetry = useCallback(async (request: StudentCaseDraftRequest) => {
        for (let attempt = 0; attempt <= AUTOSAVE_RETRY_DELAYS_MS.length; attempt += 1) {
            try {
                return await saveDraftMutation.mutateAsync(request);
            } catch (error) {
                if (!isRetriableDraftError(error) || attempt === AUTOSAVE_RETRY_DELAYS_MS.length) {
                    throw error;
                }

                if (!unmountedRef.current) {
                    setAutosaveState("retrying");
                    setErrorBanner({
                        tone: "amber",
                        title: "Sin conexion, reintentando...",
                        message: "Guardaremos tu borrador apenas el servidor vuelva a responder.",
                    });
                }

                await waitForDelay(AUTOSAVE_RETRY_DELAYS_MS[attempt]);
            }
        }

        throw new Error("Autosave retry flow exhausted unexpectedly.");
    }, [saveDraftMutation]);

    const handleMutationError = useCallback(async (error: unknown, intent: "draft" | "submit") => {
        const code = getApiErrorCode(error);

        if (code === "version_conflict") {
            setAutosaveState("error");
            setIsConflictModalOpen(true);
            return;
        }

        if (code === "already_submitted") {
            setReadOnlyOverride(true);
            setAutosaveState("saved");
            clearDraftBackup(assignmentIdRef.current);
            await detailQuery.refetch();
            return;
        }

        if (code === "deadline_passed") {
            setReadOnlyOverride(true);
            setAutosaveState("error");
            setIsDeadlineModalOpen(true);
            await detailQuery.refetch();
            return;
        }

        setAutosaveState("error");
        setErrorBanner({
            tone: "red",
            title: intent === "submit" ? "No se pudo entregar el caso" : "No se pudo guardar el borrador",
            message: getApiErrorMessage(error),
        });
    }, [detailQuery]);

    const flushDraft = useCallback(async () => {
        if (!assignmentIdRef.current || !detailRef.current || readOnlyRef.current || !dirtyRef.current) {
            return;
        }

        if (saveInFlightRef.current) {
            queuedFlushRef.current = true;
            return;
        }

        const payload = {
            answers: answersRef.current,
            version: versionRef.current,
        };
        const serializedPayload = serializeAnswers(payload.answers);

        saveInFlightRef.current = true;
        setAutosaveState("saving");

        try {
            const response = await saveDraftWithRetry(payload);
            if (unmountedRef.current) {
                return;
            }

            setVersion(response.version);
            setLastAutosavedAt(response.last_autosaved_at);
            writeDraftBackup(assignmentIdRef.current, {
                answers: payload.answers,
                version: response.version,
                ts: Date.now(),
            });

            const hasChangesAfterSave = serializeAnswers(answersRef.current) !== serializedPayload;
            setIsDirty(hasChangesAfterSave);
            setAutosaveState(hasChangesAfterSave ? "dirty" : "saved");
            if (!hasChangesAfterSave) {
                setErrorBanner(null);
            } else {
                immediateAutosaveRef.current = true;
            }
        } catch (error) {
            if (!unmountedRef.current) {
                await handleMutationError(error, "draft");
            }
        } finally {
            saveInFlightRef.current = false;
            if (queuedFlushRef.current && !unmountedRef.current) {
                queuedFlushRef.current = false;
                immediateAutosaveRef.current = true;
                setAutosaveState("dirty");
            }
        }
    }, [handleMutationError, saveDraftWithRetry]);

    useEffect(() => {
        if (!detail) {
            return;
        }

        const shouldHydrate = (
            hydratedAssignmentIdRef.current !== detail.assignment.id
            || !dirtyRef.current
            || detail.response.version !== versionRef.current
            || isReadOnlyDetail(detail)
        );

        if (!shouldHydrate) {
            setLastAutosavedAt(detail.response.last_autosaved_at);
            setSubmittedAt(detail.response.submitted_at);
            return;
        }

        hydratedAssignmentIdRef.current = detail.assignment.id;

        const draftBackup = isReadOnlyDetail(detail) ? null : readDraftBackup(detail.assignment.id);
        const serverAutosaveTimestamp = detail.response.last_autosaved_at ? Date.parse(detail.response.last_autosaved_at) : 0;
        const shouldReplayLocalDraft = Boolean(
            draftBackup
            && draftBackup.version >= detail.response.version
            && draftBackup.ts >= serverAutosaveTimestamp
            && serializeAnswers(draftBackup.answers) !== serializeAnswers(detail.response.answers),
        );

        setAnswers(shouldReplayLocalDraft && draftBackup ? draftBackup.answers : detail.response.answers);
        setVersion(detail.response.version);
        setLastAutosavedAt(detail.response.last_autosaved_at);
        setSubmittedAt(detail.response.submitted_at);
        setIsDirty(shouldReplayLocalDraft);
        setAutosaveState(
            shouldReplayLocalDraft
                ? "dirty"
                : detail.response.status === "submitted" || detail.response.last_autosaved_at
                  ? "saved"
                  : "idle",
        );
        setReadOnlyOverride(false);

        if (isReadOnlyDetail(detail)) {
            clearDraftBackup(detail.assignment.id);
        } else if (shouldReplayLocalDraft) {
            immediateAutosaveRef.current = true;
        }
    }, [detail]);

    useEffect(() => {
        if (!detail || isReadOnly || !isDirty) {
            return;
        }

        clearPendingAutosaveTimer();

        const delay = immediateAutosaveRef.current ? 0 : AUTOSAVE_DELAY_MS;
        immediateAutosaveRef.current = false;
        pendingTimerRef.current = window.setTimeout(() => {
            pendingTimerRef.current = null;
            void flushDraft();
        }, delay);

        return clearPendingAutosaveTimer;
    }, [answers, clearPendingAutosaveTimer, detail, flushDraft, isDirty, isReadOnly, version]);

    useEffect(() => () => {
        const shouldFlushPendingDraft = Boolean(
            assignmentIdRef.current
            && detailRef.current
            && dirtyRef.current
            && !readOnlyRef.current
            && !saveInFlightRef.current,
        );
        const pendingPayload = {
            answers: answersRef.current,
            version: versionRef.current,
        };

        clearPendingAutosaveTimer();
        unmountedRef.current = true;

        if (shouldFlushPendingDraft && assignmentIdRef.current) {
            void api.student.saveCaseDraft(assignmentIdRef.current, pendingPayload)
                .then((response) => {
                    writeDraftBackup(assignmentIdRef.current, {
                        answers: pendingPayload.answers,
                        version: response.version,
                        ts: Date.now(),
                    });
                })
                .catch(() => undefined);
        }
    }, [clearPendingAutosaveTimer]);

    const setLocalAnswers = useCallback((nextAnswers: Record<string, string>) => {
        if (readOnlyRef.current || !assignmentIdRef.current) {
            return;
        }

        setAnswers(nextAnswers);
        setIsDirty(true);
        setAutosaveState("dirty");
        setErrorBanner(null);
        writeDraftBackup(assignmentIdRef.current, {
            answers: nextAnswers,
            version: versionRef.current,
            ts: Date.now(),
        });
    }, []);

    const reloadAfterConflict = useCallback(async () => {
        if (!assignmentIdRef.current) {
            return;
        }

        clearDraftBackup(assignmentIdRef.current);
        setIsReloadingConflict(true);
        try {
            await detailQuery.refetch();
            setIsConflictModalOpen(false);
            setErrorBanner(null);
        } finally {
            setIsReloadingConflict(false);
        }
    }, [detailQuery]);

    const closeDeadlineModal = useCallback(() => {
        setIsDeadlineModalOpen(false);
    }, []);

    const submitCase = useCallback(async () => {
        if (!assignmentIdRef.current) {
            return;
        }

        clearPendingAutosaveTimer();

        try {
            const response = await submitMutation.mutateAsync({
                answers: answersRef.current,
                version: versionRef.current,
            });

            setVersion(response.version);
            setSubmittedAt(response.submitted_at);
            setIsDirty(false);
            setAutosaveState("saved");
            setReadOnlyOverride(false);
            clearDraftBackup(assignmentIdRef.current);
            setErrorBanner({
                tone: "emerald",
                title: "Entregado",
                message: "Entregado, esperando retroalimentacion.",
            });
        } catch (error) {
            await handleMutationError(error, "submit");
            throw error;
        }
    }, [clearPendingAutosaveTimer, handleMutationError, submitMutation]);

    return {
        detailQuery,
        answers,
        autosaveState,
        effectiveStatus,
        errorBanner,
        hasAnyAnswer,
        isConflictModalOpen,
        isDeadlineModalOpen,
        isReadOnly,
        isReloadingConflict,
        lastAutosavedAt,
        saveDraftMutation,
        setLocalAnswers,
        submittedAt,
        submitCase,
        submitMutation,
        version,
        reloadAfterConflict,
        closeDeadlineModal,
    };
}
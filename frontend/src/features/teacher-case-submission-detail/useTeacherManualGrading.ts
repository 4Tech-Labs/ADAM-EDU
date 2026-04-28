import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import type {
    TeacherCaseSubmissionDetailResponse,
    TeacherCaseSubmissionGradeResponse,
    TeacherGradeRubricLevel,
} from "@/shared/adam-types";
import { ApiError, getApiErrorCode, getApiErrorMessage } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import {
    fetchTeacherCaseSubmissionGrade,
    saveTeacherCaseSubmissionGrade,
    TEACHER_CASE_SUBMISSION_GRADE_QUERY_GC_TIME,
    UnsupportedTeacherCaseSubmissionGradePayloadVersionError,
} from "./teacherCaseSubmissionGradeApi";
import {
    buildTeacherCaseSubmissionGradeRequest,
    calculateTeacherGradeMetrics,
    canLoadTeacherManualGrading,
    cloneTeacherCaseSubmissionGrade,
    countUngradedTeacherQuestions,
    hasPublishedTeacherGrade,
    TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS,
    type TeacherManualGradingAutosaveState,
    type TeacherManualGradingBannerState,
} from "./teacherManualGradingModel";

type TeacherManualGradingMode = "disabled" | "error" | "loading" | "ready" | "unavailable";

interface UseTeacherManualGradingResult {
    mode: TeacherManualGradingMode;
    grade: TeacherCaseSubmissionGradeResponse | null;
    loadErrorMessage: string | null;
    autosaveState: TeacherManualGradingAutosaveState;
    banner: TeacherManualGradingBannerState | null;
    isDirty: boolean;
    isPublishing: boolean;
    missingQuestionCount: number;
    hasPublishedVersion: boolean;
    requiresRefresh: boolean;
    refresh: () => Promise<void>;
    publish: () => Promise<boolean>;
    setGlobalFeedback: (value: string) => void;
    setModuleFeedback: (moduleId: string, value: string) => void;
    setQuestionFeedback: (questionId: string, value: string) => void;
    setQuestionRubric: (questionId: string, value: TeacherGradeRubricLevel | null) => void;
}

function isFeatureDisabledError(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404 && getApiErrorCode(error) === "feature_disabled";
}

function buildBanner(error: unknown, intent: "draft" | "publish"): TeacherManualGradingBannerState {
    const code = getApiErrorCode(error);

    if (code === "snapshot_changed") {
        return {
            tone: "amber",
            title: "La entrega cambió",
            message: getApiErrorMessage(error),
        };
    }

    return {
        tone: "red",
        title: intent === "publish" ? "No se pudo publicar la calificación" : "No se pudo guardar el borrador",
        message: getApiErrorMessage(error),
    };
}

export function getTeacherManualGradingErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof UnsupportedTeacherCaseSubmissionGradePayloadVersionError) {
        return error.message;
    }

    if (isFeatureDisabledError(error)) {
        return "La calificación manual todavía no está habilitada en este entorno.";
    }

    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    switch (getApiErrorCode(error)) {
        case "snapshot_changed":
            return "La entrega cambió mientras calificabas. Recarga para continuar.";
        case "incomplete_grade":
            return "Debes calificar todas las preguntas visibles antes de publicar.";
        default:
            return error.message || fallback;
    }
}

export function useTeacherManualGrading(
    courseId: string,
    assignmentId: string,
    membershipId: string,
    detail: TeacherCaseSubmissionDetailResponse,
): UseTeacherManualGradingResult {
    const queryClient = useQueryClient();
    const canLoad = Boolean(courseId) && Boolean(assignmentId) && Boolean(membershipId) && canLoadTeacherManualGrading(detail);
    const [grade, setGrade] = useState<TeacherCaseSubmissionGradeResponse | null>(null);
    const [autosaveState, setAutosaveState] = useState<TeacherManualGradingAutosaveState>("idle");
    const [banner, setBanner] = useState<TeacherManualGradingBannerState | null>(null);
    const [isDirty, setIsDirty] = useState(false);
    const [isPublishing, setIsPublishing] = useState(false);
    const [requiresRefresh, setRequiresRefresh] = useState(false);

    const gradeRef = useRef<TeacherCaseSubmissionGradeResponse | null>(grade);
    const dirtyRef = useRef(isDirty);
    const saveInFlightRef = useRef(false);
    const queuedSaveRef = useRef(false);
    const autosaveTimerRef = useRef<number | null>(null);
    const unmountedRef = useRef(false);

    gradeRef.current = grade;
    dirtyRef.current = isDirty;

    const gradeQuery = useQuery({
        queryKey: queryKeys.teacher.caseSubmissionGrade(courseId, assignmentId, membershipId),
        queryFn: () => fetchTeacherCaseSubmissionGrade(courseId, assignmentId, membershipId),
        enabled: canLoad,
        staleTime: 30_000,
        gcTime: TEACHER_CASE_SUBMISSION_GRADE_QUERY_GC_TIME,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => !isFeatureDisabledError(error) && failureCount < 2,
    });

    const saveMutation = useMutation({
        mutationFn: ({ nextGrade, intent }: { nextGrade: TeacherCaseSubmissionGradeResponse; intent: "save_draft" | "publish" }) => (
            saveTeacherCaseSubmissionGrade(
                courseId,
                assignmentId,
                membershipId,
                buildTeacherCaseSubmissionGradeRequest(nextGrade, intent),
            )
        ),
    });

    const clearAutosaveTimer = useCallback(() => {
        if (autosaveTimerRef.current !== null) {
            window.clearTimeout(autosaveTimerRef.current);
            autosaveTimerRef.current = null;
        }
    }, []);

    const syncFromServer = useCallback((nextGrade: TeacherCaseSubmissionGradeResponse) => {
        const cloned = cloneTeacherCaseSubmissionGrade(nextGrade);
        setGrade(cloned);
        gradeRef.current = cloned;
        setIsDirty(false);
        dirtyRef.current = false;
        setRequiresRefresh(false);
        setAutosaveState("saved");
    }, []);

    const handleMutationError = useCallback((error: unknown, intent: "draft" | "publish") => {
        setAutosaveState("error");
        setBanner(buildBanner(error, intent));
        setRequiresRefresh(getApiErrorCode(error) === "snapshot_changed");
    }, []);

    const flushDraft = useCallback(async () => {
        if (!canLoad || !gradeRef.current || !dirtyRef.current || requiresRefresh || isPublishing) {
            return;
        }

        if (saveInFlightRef.current) {
            queuedSaveRef.current = true;
            return;
        }

        saveInFlightRef.current = true;
        setAutosaveState("saving");
        try {
            const response = await saveMutation.mutateAsync({
                nextGrade: gradeRef.current,
                intent: "save_draft",
            });
            if (unmountedRef.current) {
                return;
            }

            queryClient.setQueryData(
                queryKeys.teacher.caseSubmissionGrade(courseId, assignmentId, membershipId),
                response,
            );
            syncFromServer(response);
            setBanner(null);
        } catch (error) {
            if (!unmountedRef.current) {
                handleMutationError(error, "draft");
            }
        } finally {
            saveInFlightRef.current = false;
            if (queuedSaveRef.current) {
                queuedSaveRef.current = false;
                void flushDraft();
            }
        }
    }, [assignmentId, canLoad, courseId, handleMutationError, isPublishing, membershipId, queryClient, requiresRefresh, saveMutation, syncFromServer]);

    useEffect(() => {
        if (!gradeQuery.data) {
            return;
        }

        syncFromServer(gradeQuery.data);
    }, [gradeQuery.data, syncFromServer]);

    useEffect(() => {
        if (!canLoad || !grade || !isDirty || requiresRefresh || isPublishing) {
            return;
        }

        clearAutosaveTimer();
        autosaveTimerRef.current = window.setTimeout(() => {
            void flushDraft();
        }, TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS);

        return () => {
            clearAutosaveTimer();
        };
    }, [canLoad, clearAutosaveTimer, flushDraft, grade, isDirty, isPublishing, requiresRefresh]);

    useEffect(() => {
        return () => {
            unmountedRef.current = true;
            clearAutosaveTimer();
        };
    }, [clearAutosaveTimer]);

    const applyLocalUpdate = useCallback((recipe: (nextGrade: TeacherCaseSubmissionGradeResponse) => void) => {
        setGrade((currentGrade) => {
            if (!currentGrade) {
                return currentGrade;
            }

            const nextGrade = cloneTeacherCaseSubmissionGrade(currentGrade);
            recipe(nextGrade);
            nextGrade.publication_state = "draft";
            nextGrade.last_modified_at = new Date().toISOString();
            const metrics = calculateTeacherGradeMetrics(nextGrade);
            nextGrade.score_display = metrics.score_display;
            nextGrade.score_normalized = metrics.score_normalized;
            gradeRef.current = nextGrade;
            return nextGrade;
        });
        setBanner(null);
        setRequiresRefresh(false);
        setIsDirty(true);
        dirtyRef.current = true;
        setAutosaveState("dirty");
    }, []);

    const publish = useCallback(async () => {
        if (!gradeRef.current || saveInFlightRef.current || requiresRefresh) {
            return false;
        }

        clearAutosaveTimer();
        setIsPublishing(true);
        try {
            const response = await saveMutation.mutateAsync({
                nextGrade: gradeRef.current,
                intent: "publish",
            });
            if (unmountedRef.current) {
                return false;
            }

            queryClient.setQueryData(
                queryKeys.teacher.caseSubmissionGrade(courseId, assignmentId, membershipId),
                response,
            );
            syncFromServer(response);
            setBanner({
                tone: "emerald",
                title: "Calificación publicada",
                message: `Versión ${response.version} publicada correctamente.`,
            });
            void queryClient.invalidateQueries({
                queryKey: queryKeys.teacher.caseSubmissionDetail(assignmentId, membershipId),
            });
            void queryClient.invalidateQueries({
                queryKey: queryKeys.teacher.caseSubmissions(assignmentId),
            });
            void queryClient.invalidateQueries({
                queryKey: queryKeys.teacher.courseStudents(courseId),
            });
            return true;
        } catch (error) {
            if (!unmountedRef.current) {
                handleMutationError(error, "publish");
            }
            return false;
        } finally {
            if (!unmountedRef.current) {
                setIsPublishing(false);
            }
        }
    }, [assignmentId, clearAutosaveTimer, courseId, handleMutationError, membershipId, queryClient, requiresRefresh, saveMutation, syncFromServer]);

    const refresh = useCallback(async () => {
        clearAutosaveTimer();
        setBanner(null);
        setRequiresRefresh(false);
        await gradeQuery.refetch();
    }, [clearAutosaveTimer, gradeQuery]);

    const mode: TeacherManualGradingMode = (() => {
        if (!canLoad) {
            return "unavailable";
        }
        if (isFeatureDisabledError(gradeQuery.error)) {
            return "disabled";
        }
        if (gradeQuery.isLoading && !grade) {
            return "loading";
        }
        if (gradeQuery.error && !grade) {
            return "error";
        }
        return grade ? "ready" : "loading";
    })();

    return {
        mode,
        grade,
        loadErrorMessage: gradeQuery.error
            ? getTeacherManualGradingErrorMessage(
                gradeQuery.error,
                "No se pudo cargar la calificación manual.",
            )
            : null,
        autosaveState,
        banner,
        isDirty,
        isPublishing,
        missingQuestionCount: grade ? countUngradedTeacherQuestions(grade) : 0,
        hasPublishedVersion: hasPublishedTeacherGrade(grade),
        requiresRefresh,
        refresh,
        publish,
        setGlobalFeedback: (value: string) => {
            applyLocalUpdate((nextGrade) => {
                nextGrade.feedback_global = value;
            });
        },
        setModuleFeedback: (moduleId: string, value: string) => {
            applyLocalUpdate((nextGrade) => {
                const module = nextGrade.modules.find((currentModule) => currentModule.module_id === moduleId);
                if (module) {
                    module.feedback_module = value;
                }
            });
        },
        setQuestionFeedback: (questionId: string, value: string) => {
            applyLocalUpdate((nextGrade) => {
                for (const module of nextGrade.modules) {
                    const question = module.questions.find((currentQuestion) => currentQuestion.question_id === questionId);
                    if (question) {
                        question.feedback_question = value;
                        return;
                    }
                }
            });
        },
        setQuestionRubric: (questionId: string, value: TeacherGradeRubricLevel | null) => {
            applyLocalUpdate((nextGrade) => {
                for (const module of nextGrade.modules) {
                    const question = module.questions.find((currentQuestion) => currentQuestion.question_id === questionId);
                    if (question) {
                        question.rubric_level = value;
                        return;
                    }
                }
            });
        },
    };
}
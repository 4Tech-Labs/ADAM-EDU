/** ADAM v4.1 — AuthoringForm: formulario del profesor, fiel al mockup HtmlFormFrame.html */


import { useState, useCallback, useEffect, useRef, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { AlgorithmMode, CaseFormData, CaseType, EDADepth, StudentProfile, SuggestRequest, TeacherCourseItem } from "@/shared/adam-types";
import {
    Select, SelectContent, SelectGroup,
    SelectItem, SelectTrigger, SelectValue,
} from "@/shared/ui/select";
import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import {
    INDUSTRIAS_OPTIONS,
    STUDENT_PROFILES,
    FORM_STYLES,
    FORM_STATE_SESSION_KEY,
} from "./authoringFormConfig";
import { GroupsCombobox } from "./GroupsCombobox";
import { AlgorithmSelector } from "./AlgorithmSelector";
import { ScenarioStaleBanner } from "./ScenarioStaleBanner";

// Fingerprint of the algorithm picks AT THE TIME the scenario was generated.
// If the teacher changes any of these afterwards, the previous scenario is
// flagged as stale and a regenerate banner appears.
interface ScenarioFingerprint {
    mode: AlgorithmMode;
    primary: string | null;
    challenger: string | null;
}

function sameFingerprint(
    a: ScenarioFingerprint | null,
    b: ScenarioFingerprint,
): boolean {
    if (!a) return false;
    return (
        a.mode === b.mode
        && (a.primary ?? null) === (b.primary ?? null)
        && (a.challenger ?? null) === (b.challenger ?? null)
    );
}

interface Props {
    initialData?: CaseFormData;
    onSubmit: (data: CaseFormData) => void;
    showCancelEdit?: boolean;
    onCancelEdit?: () => void;
}

function formatCourseTargetGroupLabel(course: Pick<TeacherCourseItem, "title" | "code">): string {
    return course.code ? `${course.title} (${course.code})` : course.title;
}

function resolveCourseIdsFromTargetGroupLabels(courses: TeacherCourseItem[], labels: string[]): string[] {
    const normalizedLabels = new Set(
        labels
            .map((label) => label.trim().toLowerCase())
            .filter((label) => label.length > 0),
    );

    return courses
        .filter((course) => normalizedLabels.has(formatCourseTargetGroupLabel(course).trim().toLowerCase()))
        .map((course) => course.id);
}

    const EMPTY_TEACHER_COURSES: TeacherCourseItem[] = [];

export function AuthoringForm({
    initialData,
    onSubmit,
    showCancelEdit,
    onCancelEdit,
}: Props) {
    // ── Form state ──
    const [subject, setSubject] = useState(initialData?.courseId ?? "");
    const [syllabusModule, setSyllabusModule] = useState(initialData?.syllabusModule ?? "");
    const [topicUnit, setTopicUnit] = useState(initialData?.topicUnit ?? "");
    const restoredTargetGroupLabelsRef = useRef<string[]>(
        initialData?.targetCourseIds?.length ? [] : (initialData?.targetGroups ?? []),
    );
    const [targetCourseIds, setTargetCourseIds] = useState<string[]>(initialData?.targetCourseIds ?? []);
    const [studentProfile, setStudentProfile] = useState<StudentProfile>(initialData?.studentProfile ?? "business");

    const initialIndustry = INDUSTRIAS_OPTIONS.find((o) => o.label === initialData?.industry)?.value ?? "fintech";
    const [industry, setIndustry] = useState(initialIndustry);
    const [caseType, setCaseType] = useState<CaseType>(initialData?.caseType ?? "harvard_only");
    const [edaDepth, setEdaDepth] = useState<EDADepth | undefined>(initialData?.edaDepth);
    const [includePythonCode, setIncludePythonCode] = useState(initialData?.includePythonCode ?? false);
    const [notebookToggle, setNotebookToggle] = useState(initialData?.edaDepth === "charts_plus_code");

    const [scenarioDescription, setScenarioDescription] = useState(initialData?.scenarioDescription ?? "");
    const [guidingQuestion, setGuidingQuestion] = useState(initialData?.guidingQuestion ?? "");
    // Issue #230 — algorithm picks (replaces 5-chip free-text suggestedTechniques).
    const [algorithmMode, setAlgorithmMode] = useState<AlgorithmMode>(initialData?.algorithmMode ?? "single");
    const [algorithmPrimary, setAlgorithmPrimary] = useState<string | null>(initialData?.algorithmPrimary ?? null);
    const [algorithmChallenger, setAlgorithmChallenger] = useState<string | null>(initialData?.algorithmChallenger ?? null);

    // Scenario-anchored authoring (this PR) — fingerprint of the picks at the
    // time of the last successful scenario generation, and the most recent
    // backend coherenceWarning. Both reset together when the teacher edits the
    // scenario manually or hits Limpiar.
    const [scenarioFingerprint, setScenarioFingerprint] = useState<ScenarioFingerprint | null>(null);
    const [coherenceWarning, setCoherenceWarning] = useState<string | null>(null);

    const [availableFrom, setAvailableFrom] = useState(initialData?.availableFrom ?? "");
    const [dueAt, setDueAt] = useState(initialData?.dueAt ?? "");

    // ── Estados IA ──
    const [formAlertError, setFormAlertError] = useState<string | null>(null);
    // ── Validation ──
    const [errors, setErrors] = useState<Record<string, boolean>>({});

    // ── SessionStorage persistence ref ──
    const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // ── Restore form state from sessionStorage on mount ──
    useEffect(() => {
        const raw = sessionStorage.getItem(FORM_STATE_SESSION_KEY);
        if (!raw) return;
        try {
            const saved = JSON.parse(raw) as Record<string, unknown>;
            if (typeof saved.subject === "string") setSubject(saved.subject);
            if (typeof saved.syllabusModule === "string") setSyllabusModule(saved.syllabusModule);
            if (typeof saved.topicUnit === "string") setTopicUnit(saved.topicUnit);
            if (Array.isArray(saved.targetCourseIds)) {
                setTargetCourseIds(saved.targetCourseIds.filter((value): value is string => typeof value === "string"));
            } else if (Array.isArray(saved.targetGroups)) {
                restoredTargetGroupLabelsRef.current = saved.targetGroups.filter((value): value is string => typeof value === "string");
            }
            if (saved.studentProfile === "business" || saved.studentProfile === "ml_ds") setStudentProfile(saved.studentProfile);
            if (typeof saved.industry === "string") setIndustry(saved.industry);
            if (saved.caseType === "harvard_only" || saved.caseType === "harvard_with_eda") setCaseType(saved.caseType as CaseType);
            if (typeof saved.notebookToggle === "boolean") setNotebookToggle(saved.notebookToggle);
            if (typeof saved.scenarioDescription === "string") setScenarioDescription(saved.scenarioDescription);
            if (typeof saved.guidingQuestion === "string") setGuidingQuestion(saved.guidingQuestion);
            if (saved.algorithmMode === "single" || saved.algorithmMode === "contrast") {
                setAlgorithmMode(saved.algorithmMode);
            }
            if (typeof saved.algorithmPrimary === "string" || saved.algorithmPrimary === null) {
                setAlgorithmPrimary(saved.algorithmPrimary as string | null);
            }
            if (typeof saved.algorithmChallenger === "string" || saved.algorithmChallenger === null) {
                setAlgorithmChallenger(saved.algorithmChallenger as string | null);
            }
            if (typeof saved.availableFrom === "string") setAvailableFrom(saved.availableFrom);
            if (typeof saved.dueAt === "string") setDueAt(saved.dueAt);
        } catch {
            sessionStorage.removeItem(FORM_STATE_SESSION_KEY);
        }
    }, []);

    const teacherCoursesQuery = useQuery({
        queryKey: queryKeys.teacher.courses(),
        queryFn: () => api.teacher.getCourses(),
    });

    const selectedCourseId = subject;
    const selectedCourseDetailQuery = useQuery({
        queryKey: queryKeys.teacher.course(selectedCourseId),
        queryFn: () => api.teacher.getCourseDetail(selectedCourseId),
        enabled: !!selectedCourseId,
    });

    // ── Derived data ──
    const teacherCourses = teacherCoursesQuery.data?.courses ?? EMPTY_TEACHER_COURSES;
    const teacherCoursesById = new Map(teacherCourses.map((course) => [course.id, course]));
    const selectedCourse = teacherCourses.find((course) => course.id === selectedCourseId);
    const academicLevel = selectedCourse?.academic_level ?? "";
    const modules = selectedCourseDetailQuery.data?.syllabus?.modules ?? [];
    const selectedModule = modules.find((module) => module.module_id === syllabusModule);
    const units = selectedModule?.units ?? [];
    const selectedUnit = units.find((unit) => unit.unit_id === topicUnit);
    const targetGroups = targetCourseIds
        .map((courseId) => teacherCoursesById.get(courseId))
        .filter((course): course is TeacherCourseItem => Boolean(course))
        .map((course) => formatCourseTargetGroupLabel(course));
    const selectedIndustry = INDUSTRIAS_OPTIONS.find((option) => option.value === industry);
    const availableProfiles = caseType === "harvard_only"
        ? STUDENT_PROFILES.filter((p) => p.value !== "ml_ds")
        : STUDENT_PROFILES;
    const suggestionGenerationRef = useRef({ scenario: 0, techniques: 0 });
    const hasPersistedSyllabus = !!selectedCourseDetailQuery.data?.syllabus;

    useEffect(() => {
        if (targetCourseIds.length > 0 || restoredTargetGroupLabelsRef.current.length === 0 || teacherCourses.length === 0) {
            return;
        }

        const resolvedTargetCourseIds = resolveCourseIdsFromTargetGroupLabels(
            teacherCourses,
            restoredTargetGroupLabelsRef.current,
        );
        if (resolvedTargetCourseIds.length > 0) {
            setTargetCourseIds(resolvedTargetCourseIds);
        }
        restoredTargetGroupLabelsRef.current = [];
    }, [targetCourseIds.length, teacherCourses]);

    // ── EDA depth + notebook toggle logic ──
    // business + harvard_with_eda → edaDepth="charts_plus_explanation", no UI
    // ml_ds + harvard_with_eda → toggle ON → "charts_plus_code"; toggle OFF → "charts_plus_explanation"
    // harvard_only → edaDepth=undefined, no EDA UI
    useEffect(() => {
        if (caseType === "harvard_only") {
            setEdaDepth(undefined);
            setIncludePythonCode(false);
            setNotebookToggle(false);
        } else if (caseType === "harvard_with_eda") {
            if (studentProfile === "business") {
                setEdaDepth("charts_plus_explanation");
                setIncludePythonCode(false);
                setNotebookToggle(false);
            } else {
                setEdaDepth(notebookToggle ? "charts_plus_code" : "charts_plus_explanation");
                setIncludePythonCode(notebookToggle);
            }
        }
    }, [caseType, studentProfile, notebookToggle]);

    // ── Debounced sessionStorage persist ──
    useEffect(() => {
        if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
        persistTimerRef.current = setTimeout(() => {
            try {
                sessionStorage.setItem(FORM_STATE_SESSION_KEY, JSON.stringify({
                    subject, syllabusModule, topicUnit, targetGroups, targetCourseIds, studentProfile,
                    industry, caseType, notebookToggle,
                    scenarioDescription, guidingQuestion,
                    algorithmMode, algorithmPrimary, algorithmChallenger,
                    availableFrom, dueAt,
                }));
            } catch {
                // sessionStorage quota exceeded or unavailable — fail silently
            }
        }, 300);
        return () => {
            if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
        };
    }, [subject, syllabusModule, topicUnit, targetGroups, targetCourseIds, studentProfile, industry, caseType,
        notebookToggle, scenarioDescription, guidingQuestion,
        algorithmMode, algorithmPrimary, algorithmChallenger,
        availableFrom, dueAt]);

    const invalidateSuggestionResponses = useCallback(() => {
        suggestionGenerationRef.current.scenario += 1;
        suggestionGenerationRef.current.techniques += 1;
    }, []);

    // ── Validation CanSuggest ──
    const canSuggest =
        !!subject &&
        targetCourseIds.length > 0 &&
        targetGroups.length > 0 &&
        !!syllabusModule &&
        !!industry;

    // ── Validation CanSubmit ──
    const isAlgorithmsRequired = caseType === "harvard_with_eda" || studentProfile === "ml_ds";
    const hasValidTopicUnit = units.length === 0 || !!topicUnit;
    const hasValidAlgorithmPicks =
        !!algorithmPrimary
        && (algorithmMode === "single"
            || (!!algorithmChallenger && algorithmPrimary.toLowerCase() !== algorithmChallenger.toLowerCase()));

    // Scenario suggestion gate (this PR): when algorithm picks are required
    // (harvard_with_eda or ml_ds), the teacher MUST pick the algorithm BEFORE
    // generating the scenario, so the LLM prompt can be anchored to that
    // family. Otherwise we fall back to the legacy non-anchored prompt.
    const canSuggestScenario =
        canSuggest && (!isAlgorithmsRequired || hasValidAlgorithmPicks);
    const canSubmit =
        !!subject &&
        !!syllabusModule &&
        hasValidTopicUnit &&
        targetCourseIds.length > 0 &&
        !!industry &&
        !!scenarioDescription.trim() &&
        !!guidingQuestion.trim() &&
        !!availableFrom &&
        !!dueAt &&
        (!isAlgorithmsRequired || hasValidAlgorithmPicks);

    const buildSuggestPayload = useCallback((): SuggestRequest => {
        const moduleName = selectedModule?.module_title ?? "";
        const unitName = selectedUnit?.title ?? "";
        const industryLabel = selectedIndustry?.label ?? industry;

        return {
            subject: selectedCourse?.title ?? "",
            academicLevel: selectedCourse?.academic_level ?? "",
            targetGroups,
            syllabusModule: moduleName,
            topicUnit: unitName,
            industry: industryLabel,
            studentProfile,
            caseType,
            edaDepth,
            includePythonCode,
            scenarioDescription,
            guidingQuestion,
            mode: algorithmMode,
            // Scenario-anchored suggest (this PR): only forward picks when
            // they are required by the case shape AND actually selected.
            // Off-anchor calls keep the legacy prompt intact.
            algorithmPrimary: isAlgorithmsRequired ? algorithmPrimary : null,
            algorithmChallenger:
                isAlgorithmsRequired && algorithmMode === "contrast" ? algorithmChallenger : null,
        };
    }, [
        algorithmMode,
        algorithmPrimary,
        algorithmChallenger,
        caseType,
        edaDepth,
        guidingQuestion,
        includePythonCode,
        industry,
        isAlgorithmsRequired,
        scenarioDescription,
        selectedIndustry,
        selectedCourse,
        selectedModule,
        selectedUnit,
        studentProfile,
        targetGroups,
    ]);

    const scenarioMutation = useMutation({
        mutationFn: (payload: SuggestRequest) => api.suggest("scenario", payload),
    });

    const techniquesMutation = useMutation({
        mutationFn: (payload: SuggestRequest) => api.suggest("techniques", payload),
    });

    const mutationError =
        scenarioMutation.error instanceof Error
            ? scenarioMutation.error.message
            : techniquesMutation.error instanceof Error
                ? techniquesMutation.error.message
                : null;

    const resetSuggestionFeedback = useCallback(() => {
        scenarioMutation.reset();
        techniquesMutation.reset();
        setFormAlertError(null);
    }, [scenarioMutation, techniquesMutation]);

    const handleSuggestScenario = useCallback(() => {
        if (!canSuggestScenario || scenarioMutation.isPending) {
            return;
        }

        resetSuggestionFeedback();
        setCoherenceWarning(null);
        const generation = suggestionGenerationRef.current.scenario + 1;
        suggestionGenerationRef.current.scenario = generation;

        // Snapshot the picks AT REQUEST TIME so the fingerprint reflects what
        // the LLM was actually anchored to, not whatever the form state is at
        // the (later) success callback.
        const fingerprint: ScenarioFingerprint = {
            mode: algorithmMode,
            primary: isAlgorithmsRequired ? algorithmPrimary : null,
            challenger:
                isAlgorithmsRequired && algorithmMode === "contrast" ? algorithmChallenger : null,
        };

        scenarioMutation.mutate(buildSuggestPayload(), {
            onSuccess: (data) => {
                if (suggestionGenerationRef.current.scenario !== generation) {
                    return;
                }

                if (data.scenarioDescription) {
                    setScenarioDescription(data.scenarioDescription);
                }
                if (data.guidingQuestion) {
                    setGuidingQuestion(data.guidingQuestion);
                }
                setScenarioFingerprint(fingerprint);
                setCoherenceWarning(
                    typeof data.coherenceWarning === "string" && data.coherenceWarning
                        ? data.coherenceWarning
                        : null,
                );
            },
        });
    }, [
        algorithmChallenger,
        algorithmMode,
        algorithmPrimary,
        buildSuggestPayload,
        canSuggestScenario,
        isAlgorithmsRequired,
        resetSuggestionFeedback,
        scenarioMutation,
    ]);

    const handleSuggestTechniques = useCallback(() => {
        if (!canSuggest || techniquesMutation.isPending) {
            return;
        }

        resetSuggestionFeedback();
        const generation = suggestionGenerationRef.current.techniques + 1;
        suggestionGenerationRef.current.techniques = generation;

        techniquesMutation.mutate(buildSuggestPayload(), {
            onSuccess: (data) => {
                if (suggestionGenerationRef.current.techniques !== generation) {
                    return;
                }

                // Always sync state with the response so a backend null
                // (cross-family / off-catalog / unsnappable baseline) clears
                // the previous selection instead of leaving a stale pick.
                setAlgorithmPrimary(
                    typeof data.algorithmPrimary === "string" && data.algorithmPrimary
                        ? data.algorithmPrimary
                        : null,
                );
                if (algorithmMode === "contrast") {
                    setAlgorithmChallenger(
                        typeof data.algorithmChallenger === "string" && data.algorithmChallenger
                            ? data.algorithmChallenger
                            : null,
                    );
                } else {
                    setAlgorithmChallenger(null);
                }
                setErrors((prev) => ({ ...prev, suggestedTechniques: false }));
            },
        });
    }, [algorithmMode, buildSuggestPayload, canSuggest, resetSuggestionFeedback, techniquesMutation]);

    // ── B6: Cascading resets ──
    const handleSubjectChange = (id: string) => {
        invalidateSuggestionResponses();
        setSubject(id);
        setSyllabusModule("");
        setTopicUnit("");
        setTargetCourseIds([]);
        setErrors((prev) => ({ ...prev, asignatura: false, modulo: false, topicUnit: false }));
    };

    const handleSyllabusModuleChange = (id: string) => {
        invalidateSuggestionResponses();
        setSyllabusModule(id);
        setTopicUnit("");
        setErrors((prev) => ({ ...prev, modulo: false, topicUnit: false }));
    };

    const handleTopicUnitChange = (id: string) => {
        invalidateSuggestionResponses();
        setTopicUnit(id);
        setErrors((prev) => ({ ...prev, topicUnit: false }));
    };

    const addTargetGroup = useCallback((value: string) => {
        const normalizedCourseId = value.trim();
        if (!normalizedCourseId) return;
        if (targetCourseIds.includes(normalizedCourseId)) return;
        invalidateSuggestionResponses();
        setTargetCourseIds((prev) => [...prev, normalizedCourseId]);
        setErrors((prev) => ({ ...prev, targetGroups: false }));
    }, [invalidateSuggestionResponses, targetCourseIds]);

    const removeTargetGroup = useCallback((group: string) => {
        invalidateSuggestionResponses();
        setTargetCourseIds((prev) => prev.filter((value) => value !== group));
    }, [invalidateSuggestionResponses]);

    // ── Issue #230: algorithm selector change handler ──
    const handleAlgorithmChange = useCallback(
        (next: { mode: AlgorithmMode; primary: string | null; challenger: string | null }) => {
            setAlgorithmMode(next.mode);
            setAlgorithmPrimary(next.primary);
            setAlgorithmChallenger(next.challenger);
            setErrors((prev) => ({ ...prev, suggestedTechniques: false }));
        },
        [],
    );

    // ── Component Events Triggering Warning ──
    // Manual edits invalidate the fingerprint (the scenario is no longer the
    // verbatim LLM output) and clear any prior coherenceWarning, since the
    // teacher is taking ownership of the text.
    const onChangeScenarioDescription = (val: string) => {
        invalidateSuggestionResponses();
        setScenarioDescription(val);
        setScenarioFingerprint(null);
        setCoherenceWarning(null);
    };
    const onChangeGuidingQuestion = (val: string) => {
        invalidateSuggestionResponses();
        setGuidingQuestion(val);
        setScenarioFingerprint(null);
        setCoherenceWarning(null);
    };
    const onIndustryChange = (val: string) => {
        invalidateSuggestionResponses();
        setIndustry(val);
    };
    const onStudentProfileChange = (val: string) => {
        invalidateSuggestionResponses();
        setStudentProfile(val as StudentProfile);
    };
    const onCaseTypeChange = (val: CaseType) => {
        invalidateSuggestionResponses();
        if (val === "harvard_only" && studentProfile === "ml_ds") {
            setStudentProfile("business");
        }
        setCaseType(val);
    };
    const onChangeAvailableFrom = (val: string) => {
        setAvailableFrom(val);
        setFormAlertError(null);
        if (val) setErrors((prev) => ({ ...prev, availableFrom: false, dateOrder: false }));
    };
    const onChangeDueAt = (val: string) => {
        setDueAt(val);
        setFormAlertError(null);
        if (val) setErrors((prev) => ({ ...prev, dueAt: false, dateOrder: false }));
    };
    // ── Submit ──
    const handleSubmit = (e: FormEvent) => {
            e.preventDefault();
            setFormAlertError(null);
            const newErrors: Record<string, boolean> = {};
            if (!subject) newErrors.asignatura = true;
            if (!syllabusModule) newErrors.modulo = true;
            if (units.length > 0 && !topicUnit) newErrors.topicUnit = true;
            if (targetCourseIds.length === 0) newErrors.targetGroups = true;
            if (!industry) newErrors.industria = true;
            if (!scenarioDescription.trim()) newErrors.scenario = true;
            if (!guidingQuestion.trim()) newErrors.guidingQuestion = true;
            if (!availableFrom) newErrors.availableFrom = true;
            if (!dueAt) newErrors.dueAt = true;
            if (isAlgorithmsRequired && !hasValidAlgorithmPicks) newErrors.suggestedTechniques = true;
            // edaDepth is calculated automatically — no user validation needed

            // Validate date order after presence checks
            if (availableFrom && dueAt && new Date(dueAt) < new Date(availableFrom)) {
                newErrors.dateOrder = true;
                setFormAlertError("La Fecha de Cierre no puede ser anterior a la Disponibilidad.");
            }

            if (Object.keys(newErrors).length > 0) {
                setErrors(newErrors);
                // Scroll to top unless the only error is date ordering
                const firstId = Object.keys(newErrors)[0];
                if (firstId === "dateOrder") {
                    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
                } else {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
                return;
            }

            setErrors({});

            const formData: CaseFormData = {
                courseId: selectedCourseId,
                subject: selectedCourse?.title ?? "",
                academicLevel,
                targetGroups,
                targetCourseIds,
                syllabusModule,
                topicUnit,
                industry: selectedIndustry?.label ?? industry,
                studentProfile,
                caseType,
                edaDepth,
                includePythonCode,
                scenarioDescription,
                guidingQuestion,
                algorithmMode: isAlgorithmsRequired ? algorithmMode : "single",
                algorithmPrimary: isAlgorithmsRequired ? algorithmPrimary : null,
                algorithmChallenger:
                    isAlgorithmsRequired && algorithmMode === "contrast" ? algorithmChallenger : null,
                availableFrom,
                dueAt
            };

            onSubmit(formData);
        };

    // ── Clear ──
    const clearForm = () => {
        sessionStorage.removeItem(FORM_STATE_SESSION_KEY);
        invalidateSuggestionResponses();
        setSubject("");
        setSyllabusModule("");
        setTopicUnit("");
        setIndustry("fintech");
        setStudentProfile("business");
        setTargetCourseIds([]);
        setScenarioDescription("");
        setGuidingQuestion("");
        setAlgorithmMode("single");
        setAlgorithmPrimary(null);
        setAlgorithmChallenger(null);
        setScenarioFingerprint(null);
        setCoherenceWarning(null);
        setErrors({});
        scenarioMutation.reset();
        techniquesMutation.reset();
        setFormAlertError(null);
        setCaseType("harvard_only");
        setEdaDepth(undefined);
        setIncludePythonCode(false);
        setNotebookToggle(false);
        setAvailableFrom("");
        setDueAt("");
    };

    const ErrorMsg = ({ show }: { show: boolean }) =>
        show ? (
            <p role="alert" className="mt-1.5 text-xs text-red-500 font-medium flex items-center gap-1">
                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Campo requerido
            </p>
        ) : null;

    return (
        <>
            <style>{FORM_STYLES}</style>
            <div
                className="teacher-form flex items-center justify-center p-4 py-10"
                style={
                    {
                        "--adam-brand": "#0144a0",
                        "--adam-brand-dark": "#00337a",
                        "--adam-brand-light": "#e8f0fe",
                        "--adam-error": "#ef4444",
                        "--adam-success": "#16a34a",
                    } as React.CSSProperties
                }
            >
                <div className="w-full max-w-3xl fade-in-up">
                    <div className="bg-white rounded-2xl shadow-[0_12px_48px_-12px_rgba(0,0,0,0.12)] border border-slate-200 overflow-hidden">
                        {/* ── Required note ── */}
                        <div className="px-8 pt-5 pb-0 flex justify-end">
                            <span className="text-[11.5px] text-slate-500">
                                <span className="text-red-500 font-semibold">*</span> Campos obligatorios
                            </span>
                        </div>

                        <form onSubmit={handleSubmit} noValidate className="px-8 pt-5 pb-8 space-y-8">
                            {/* ════════════════ SECCIÓN 1 — Contexto Académico ════════════════ */}
                            <fieldset>
                                <legend className="w-full flex items-center gap-3.5 pb-3 mb-6 section-divider">
                                    <span className="step-badge" aria-hidden="true">1</span>
                                    <span className="text-base font-bold uppercase tracking-widest text-[#0144a0]">Contexto Académico</span>
                                </legend>

                                <div className="space-y-6">
                                    {/* Asignatura + Nivel */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                                        <div>
                                            <label htmlFor="field-asignatura" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Asignatura <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <Select value={subject} onValueChange={handleSubjectChange}>
                                                <SelectTrigger
                                                    id="field-asignatura"
                                                    className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 ${errors.asignatura ? "input-error" : ""}`}
                                                >
                                                    <SelectValue placeholder="Seleccione una asignatura..." />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {teacherCourses.map((course) => (
                                                            <SelectItem key={course.id} value={course.id}>{course.title}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.asignatura} />
                                            {teacherCoursesQuery.error instanceof Error ? (
                                                <p className="field-hint text-red-500">{teacherCoursesQuery.error.message}</p>
                                            ) : null}
                                        </div>

                                        <div>
                                            <label htmlFor="field-nivel" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Nivel Académico <span className="text-xs font-normal text-slate-400 ml-1">(Automático)</span>
                                            </label>
                                            <input
                                                type="text"
                                                id="field-nivel"
                                                readOnly
                                                value={academicLevel}
                                                placeholder="Se completa al elegir asignatura"
                                                className="input-base w-full rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-600 cursor-not-allowed focus:outline-none"
                                            />
                                        </div>
                                    </div>

                                    {/* Grupos */}
                                    <div>
                                        <label htmlFor="field-grupos" className="block text-sm font-semibold text-slate-700 mb-2">
                                            Grupos Destino <span className="text-red-500" aria-hidden="true">*</span>
                                        </label>
                                        <GroupsCombobox
                                            courses={teacherCourses}
                                            value={targetCourseIds}
                                            onAdd={addTargetGroup}
                                            onRemove={removeTargetGroup}
                                            hasError={!!errors.targetGroups}
                                        />
                                        {errors.targetGroups && <ErrorMsg show={true} />}
                                        <p className="field-hint">Seleccione los grupos o secciones que recibirán este caso.</p>
                                    </div>

                                    {/* Módulo + Unidad */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-2">
                                        <div>
                                            <label htmlFor="field-modulo" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Módulo del Syllabus <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <Select
                                                disabled={!subject}
                                                value={syllabusModule}
                                                onValueChange={handleSyllabusModuleChange}
                                            >
                                                <SelectTrigger
                                                    id="field-modulo"
                                                    className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 disabled:bg-slate-50 disabled:text-slate-400 ${errors.modulo ? "input-error" : ""}`}
                                                >
                                                    <SelectValue placeholder={subject ? "Seleccione un módulo..." : "Primero seleccione asignatura..."} />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {modules.map((m) => (
                                                            <SelectItem key={m.module_id} value={m.module_id}>{m.module_title}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.modulo} />
                                            {subject && !hasPersistedSyllabus ? (
                                                <p className="field-hint text-amber-700">Este curso aun no tiene un syllabus guardado.</p>
                                            ) : null}
                                        </div>

                                        <div>
                                            <label htmlFor="field-unidad" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Unidad Temática <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <Select
                                                disabled={!syllabusModule || units.length === 0}
                                                value={topicUnit}
                                                onValueChange={handleTopicUnitChange}
                                            >
                                                <SelectTrigger
                                                    id="field-unidad"
                                                    className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 disabled:bg-slate-50 disabled:text-slate-400 ${errors.topicUnit ? "input-error" : ""}`}
                                                >
                                                    <SelectValue placeholder={!syllabusModule ? "Seleccione módulo primero..." : units.length === 0 ? "Este módulo no define unidades" : "Seleccione una unidad..."} />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {units.map((u) => (
                                                            <SelectItem key={u.unit_id} value={u.unit_id}>{u.title}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.topicUnit} />
                                        </div>
                                    </div>

                                </div>
                            </fieldset>

                            {/* ════════════════ SECCIÓN 2 — Configuración del Escenario ════════════════ */}
                            <fieldset>
                                <legend className="w-full flex items-center gap-3.5 pb-3 mb-6 section-divider">
                                    <span className="step-badge" aria-hidden="true">2</span>
                                    <span className="text-base font-bold uppercase tracking-widest text-[#0144a0]">Configuración del Escenario</span>
                                </legend>

                                <div className="space-y-5">
                                    {/* Case Type toggle */}
                                    <div>
                                        <p className="text-sm font-semibold text-slate-700 mb-3">Alcance del caso generado</p>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3" role="radiogroup">
                                            {/* Harvard Only */}
                                            <div
                                                role="radio"
                                                aria-checked={caseType === "harvard_only"}
                                                tabIndex={0}
                                                onClick={() => onCaseTypeChange("harvard_only")}
                                                className={`scope-card p-4 select-none ${caseType === "harvard_only" ? "active" : ""}`}
                                            >
                                                <span className="scope-check" aria-hidden="true">✓</span>
                                                <div className="flex items-start gap-3.5">
                                                    <div className={`mt-0.5 p-2.5 rounded-full flex-shrink-0 transition-colors ${caseType === "harvard_only" ? "bg-[#0144a0] text-white" : "bg-slate-100 text-slate-500"}`}>
                                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                                                        </svg>
                                                    </div>
                                                    <div>
                                                        <p className={`text-sm font-bold transition-colors ${caseType === "harvard_only" ? "text-[#0144a0]" : "text-slate-600"}`}>Solo Caso Harvard</p>
                                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">Narrativa, dilema y preguntas de discusión.</p>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Harvard with EDA */}
                                            <div
                                                role="radio"
                                                aria-checked={caseType === "harvard_with_eda"}
                                                tabIndex={0}
                                                onClick={() => onCaseTypeChange("harvard_with_eda")}
                                                className={`scope-card p-4 select-none ${caseType === "harvard_with_eda" ? "active" : ""}`}
                                            >
                                                <span className="scope-check" aria-hidden="true">✓</span>
                                                <div className="flex items-start gap-3.5">
                                                    <div className={`mt-0.5 p-2.5 rounded-full flex-shrink-0 transition-colors ${caseType === "harvard_with_eda" ? "bg-[#0144a0] text-white" : "bg-slate-100 text-slate-500"}`}>
                                                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                                            <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                                                        </svg>
                                                    </div>
                                                    <div>
                                                        <p className={`text-sm font-bold transition-colors ${caseType === "harvard_with_eda" ? "text-[#0144a0]" : "text-slate-600"}`}>Caso + Análisis de Datos (EDA)</p>
                                                        <p className="text-xs text-slate-500 mt-1 leading-relaxed">Incluye análisis de datos, visualizaciones y, si aplica, notebook ejecutable en Google Colab.</p>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Perfil de Estudiante */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 pt-2">
                                        <div>
                                            <label htmlFor="field-studentProfile" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Perfil del curso <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <Select value={studentProfile} onValueChange={onStudentProfileChange}>
                                                <SelectTrigger
                                                    id="field-studentProfile"
                                                    className="input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800"
                                                >
                                                    <SelectValue placeholder="Selecciona un perfil..." />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {availableProfiles.map((opt) => (
                                                            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                        </div>
                                    </div>

                                    {/* Notebook toggle — only for ml_ds + harvard_with_eda */}
                                    {caseType === "harvard_with_eda" && studentProfile === "ml_ds" && (
                                        <div className="p-4 border border-blue-100 bg-blue-50/30 rounded-xl">
                                            <label className="flex items-center gap-3 cursor-pointer select-none">
                                                <button
                                                    type="button"
                                                    role="switch"
                                                    aria-checked={notebookToggle}
                                                    onClick={() => {
                                                        invalidateSuggestionResponses();
                                                        setNotebookToggle((prev) => !prev);
                                                    }}
                                                    className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${notebookToggle ? "bg-[#0144a0]" : "bg-slate-300"}`}
                                                >
                                                    <span
                                                        className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform duration-200 ${notebookToggle ? "translate-x-5" : "translate-x-0"}`}
                                                    />
                                                </button>
                                                <div>
                                                    <span className="text-sm font-semibold text-slate-700">Incluir notebook ejecutable en Google Colab</span>
                                                    <p className="text-xs text-slate-500 mt-0.5">Genera código Python listo para ejecutar con el dataset sintético del caso.</p>
                                                </div>
                                            </label>
                                        </div>
                                    )}

                                    {/* Industria */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 border-t border-slate-100 pt-3">
                                        <div>
                                            <label htmlFor="field-industria" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Industria / Sector <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <Select value={industry} onValueChange={onIndustryChange}>
                                                <SelectTrigger
                                                    id="field-industria"
                                                    className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 ${errors.industria ? "input-error" : ""}`}
                                                >
                                                    <SelectValue placeholder="Selecciona una industria..." />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {INDUSTRIAS_OPTIONS.map((opt) => (
                                                            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.industria} />
                                        </div>
                                    </div>

                                    {/* Algoritmos / Técnicas — Issue #230 (mode toggle 1 deep | 2 contrast + canonical dropdowns).
                                        Anchored authoring (this PR): rendered BEFORE the scenario textarea so the
                                        teacher locks the algorithm first, and the LLM scenario can be anchored to
                                        the corresponding family. Order: case type → profile → notebook → industry →
                                        algoritmos → escenario → pregunta guía. */}
                                    {isAlgorithmsRequired && (
                                        <AlgorithmSelector
                                            profile={studentProfile}
                                            caseType={caseType}
                                            mode={algorithmMode}
                                            primary={algorithmPrimary}
                                            challenger={algorithmChallenger}
                                            onChange={handleAlgorithmChange}
                                            onSuggest={handleSuggestTechniques}
                                            isSuggestPending={techniquesMutation.isPending}
                                            canSuggest={canSuggest}
                                            hasError={!!errors.suggestedTechniques}
                                        />
                                    )}

                                    {/* Sugestión global error flag */}
                                    {(formAlertError || mutationError) && (
                                        <div className="p-3 mb-2 rounded border border-red-200 bg-red-50 text-red-600 text-[13px] font-medium flex items-center gap-2">
                                            <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12A9 9 0 113 12a9 9 0 0118 0z" />
                                            </svg>
                                            {formAlertError ?? mutationError}
                                        </div>
                                    )}

                                    {/* Descripción y Pregunta Guía */}
                                    <div className="space-y-4 pt-1">
                                        <div>
                                            <label htmlFor="field-scenarioDescription" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Descripción del Escenario (Obligatorio) <span className="text-red-500" aria-hidden="true">*</span>
                                                <button
                                                    type="button"
                                                    onClick={handleSuggestScenario}
                                                    disabled={!canSuggestScenario || scenarioMutation.isPending}
                                                    title={
                                                        canSuggestScenario
                                                            ? undefined
                                                            : isAlgorithmsRequired && !hasValidAlgorithmPicks
                                                                ? "Primero selecciona el algoritmo arriba para que el escenario sea coherente con esa familia."
                                                                : undefined
                                                    }
                                                    className={`ml-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-bold text-[#0144a0] bg-blue-50 border border-blue-200 rounded-lg transition-all ${!canSuggestScenario ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-blue-100 hover:border-blue-300 hover:shadow-sm active:scale-[0.97]"}`}
                                                >
                                                    {scenarioMutation.isPending ? (
                                                        <><span className="animate-spin w-3 h-3 border-2 border-[#0144a0] border-t-transparent rounded-full"></span> Generando...</>
                                                    ) : (
                                                        <>🪄 Sugerir Caso y Dilema</>
                                                    )}
                                                </button>
                                            </label>
                                            <textarea
                                                id="field-scenarioDescription"
                                                rows={6}
                                                value={scenarioDescription}
                                                onChange={(e) => onChangeScenarioDescription(e.target.value)}
                                                placeholder="Describe la problemática o narrativa gerencial base..."
                                                className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 resize-none leading-relaxed ${errors.scenario ? "input-error" : ""}`}
                                            />
                                            <ErrorMsg show={!!errors.scenario} />

                                            {/* Scenario-anchored authoring (this PR): banners surface coherence
                                                risk between the algorithm pick and the generated scenario.
                                                Neither blocks submission. */}
                                            {scenarioFingerprint
                                                && isAlgorithmsRequired
                                                && hasValidAlgorithmPicks
                                                && !sameFingerprint(scenarioFingerprint, {
                                                    mode: algorithmMode,
                                                    primary: algorithmPrimary,
                                                    challenger:
                                                        algorithmMode === "contrast" ? algorithmChallenger : null,
                                                }) ? (
                                                <ScenarioStaleBanner
                                                    variant="stale"
                                                    onRegenerate={handleSuggestScenario}
                                                    isRegenerating={scenarioMutation.isPending}
                                                    canRegenerate={canSuggestScenario}
                                                />
                                            ) : null}
                                            {coherenceWarning ? (
                                                <ScenarioStaleBanner
                                                    variant="warning"
                                                    message={coherenceWarning}
                                                />
                                            ) : null}
                                        </div>

                                        <div>
                                            <label htmlFor="field-guidingQuestion" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Pregunta guía del caso (Obligatoria) <span className="text-red-500" aria-hidden="true">*</span>
                                            </label>
                                            <textarea
                                                id="field-guidingQuestion"
                                                rows={3}
                                                value={guidingQuestion}
                                                onChange={(e) => onChangeGuidingQuestion(e.target.value)}
                                                placeholder="Ej: ¿Qué factores macroeconómicos reducirán la merma un 15%?"
                                                className={`input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 ${errors.guidingQuestion ? "input-error" : ""}`}
                                            />
                                            <ErrorMsg show={!!errors.guidingQuestion} />
                                        </div>
                                    </div>
                                </div>
                            </fieldset>

                            {/* ════════════════ SECCIÓN 3 — Configuración de la Entrega ════════════════ */}
                            <fieldset>
                                <legend className="w-full flex items-center gap-3.5 pb-3 mb-6 section-divider">
                                    <span className="step-badge" aria-hidden="true">3</span>
                                    <span className="text-base font-bold uppercase tracking-widest text-[#0144a0]">Configuración de la Entrega</span>
                                </legend>
                                <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-3">
                                    <div>
                                        <label htmlFor="field-fecha-inicio" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                            Fecha de Disponibilidad <span className="text-red-500" aria-hidden="true">*</span>
                                        </label>
                                        <input
                                            type="datetime-local"
                                            id="field-fecha-inicio"
                                            value={availableFrom}
                                            onChange={(e) => onChangeAvailableFrom(e.target.value)}
                                            className={`input-base w-full rounded-lg border bg-white px-3.5 py-2.5 text-sm text-slate-800 cursor-pointer ${errors.availableFrom ? "border-red-400 input-error" : "border-slate-200"}`}
                                        />
                                        <ErrorMsg show={!!errors.availableFrom} />
                                    </div>
                                    <div className="date-arrow" aria-hidden="true">
                                        <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M17 8l4 4m0 0l-4 4m4-4H3" />
                                        </svg>
                                    </div>
                                    <div>
                                        <label htmlFor="field-fecha-cierre" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                            Fecha de Cierre <span className="text-red-500" aria-hidden="true">*</span>
                                        </label>
                                        <input
                                            type="datetime-local"
                                            id="field-fecha-cierre"
                                            value={dueAt}
                                            onChange={(e) => onChangeDueAt(e.target.value)}
                                            className={`input-base w-full rounded-lg border bg-white px-3.5 py-2.5 text-sm text-slate-800 cursor-pointer ${errors.dueAt ? "border-red-400 input-error" : "border-slate-200"}`}
                                        />
                                        <ErrorMsg show={!!errors.dueAt} />
                                    </div>
                                </div>
                                {errors.dateOrder && (
                                    <div className="mt-3 text-red-500 text-sm font-medium">⚠️ La fecha de cierre no puede ser anterior a la disponibilidad.</div>
                                )}
                            </fieldset>

                            {/* ── Footer ── */}
                            <div>
                                <hr className="footer-divider mb-6" />
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-3">
                                        <button
                                            type="button"
                                            onClick={clearForm}
                                            className="text-sm font-medium text-slate-500 hover:text-red-500 transition-colors flex items-center gap-1.5 rounded"
                                        >
                                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                            </svg>
                                            Limpiar todo
                                        </button>

                                        {showCancelEdit && onCancelEdit && (
                                            <button
                                                type="button"
                                                onClick={onCancelEdit}
                                                className="text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors"
                                            >
                                                Cancelar edición
                                            </button>
                                        )}
                                    </div>

                                    <button
                                        type="submit"
                                        disabled={!canSubmit}
                                        className={`flex items-center gap-2 rounded-xl bg-[#0144a0] px-7 py-2.5 text-sm font-bold text-white shadow-md transition-all ${canSubmit ? "hover:bg-[#00337a] hover:shadow-lg active:scale-[0.98]" : "opacity-50 cursor-not-allowed"}`}
                                    >
                                        {caseType === "harvard_with_eda" ? "Generar Caso + EDA" : "Generar Caso Harvard"}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </>
    );
}

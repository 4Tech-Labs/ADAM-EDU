/** ADAM v4.1 — AuthoringForm: formulario del profesor, fiel al mockup HtmlFormFrame.html */


import { useState, useCallback, useEffect, type KeyboardEvent, type FormEvent } from "react";
import type { CaseFormData, CaseType, EDADepth, StudentProfile, IntentType } from "@/shared/adam-types";
import {
    Select, SelectContent, SelectGroup,
    SelectItem, SelectTrigger, SelectValue,
} from "@/shared/ui/select";
import { api } from "@/shared/api";
import {
    professorDB,
    INDUSTRIAS_OPTIONS,
    STUDENT_PROFILES,
    FORM_STYLES
} from "./authoringFormConfig";

interface Props {
    initialData?: CaseFormData;
    onSubmit: (data: CaseFormData) => void;
    showCancelEdit?: boolean;
    onCancelEdit?: () => void;
}

export function AuthoringForm({
    onSubmit,
    showCancelEdit,
    onCancelEdit,
}: Props) {
    // ── Form state ──
    const [subject, setSubject] = useState("");
    const [syllabusModule, setSyllabusModule] = useState("");
    const [topicUnit, setTopicUnit] = useState("");
    const [targetGroups, setTargetGroups] = useState<string[]>([]);
    const [studentProfile, setStudentProfile] = useState<StudentProfile>("business");

    const [industry, setIndustry] = useState("fintech");
    const [caseType, setCaseType] = useState<CaseType>("harvard_only");
    const [edaDepth, setEdaDepth] = useState<EDADepth | undefined>(undefined);
    const [includePythonCode, setIncludePythonCode] = useState(false);
    const [notebookToggle, setNotebookToggle] = useState(false);

    const [scenarioDescription, setScenarioDescription] = useState("");
    const [guidingQuestion, setGuidingQuestion] = useState("");
    const [suggestedTechniques, setSuggestedTechniques] = useState<string[]>([]);
    const [algoInput, setAlgoInput] = useState("");

    const [availableFrom, setAvailableFrom] = useState("");
    const [dueAt, setDueAt] = useState("");

    // ── Estados IA ──
    const [isSuggestingScenario, setIsSuggestingScenario] = useState(false);
    const [isSuggestingTechniques, setIsSuggestingTechniques] = useState(false);
    const [suggestError, setSuggestError] = useState<string | null>(null);
    const [areTechniquesStale, setAreTechniquesStale] = useState(false);

    // ── Validation ──
    const [errors, setErrors] = useState<Record<string, boolean>>({});

    // ── Derived data ──
    const selectedCourse = professorDB.courses.find((c) => c.id === subject);
    const academicLevel = selectedCourse?.level ?? "";
    const modules = selectedCourse?.syllabus ?? [];
    const selectedModule = modules.find((m) => m.id === syllabusModule);
    const units = selectedModule?.units ?? [];

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

    const markStale = useCallback(() => {
        if (suggestedTechniques.length > 0) {
            setAreTechniquesStale(true);
        }
    }, [suggestedTechniques]);

    // ── Validation CanSuggest ──
    const canSuggest =
        !!subject &&
        targetGroups.length > 0 &&
        !!syllabusModule &&
        !!industry;

    const fetchSuggestion = async (intent: IntentType) => {
        if (!canSuggest) return;

        const isScenario = intent === "scenario" || intent === "both";
        const isTechniques = intent === "techniques" || intent === "both";

        if (isScenario) setIsSuggestingScenario(true);
        if (isTechniques) setIsSuggestingTechniques(true);
        setSuggestError(null);

        try {
            const selectedCourseForAI = professorDB.courses.find(c => c.id === subject);
            const modulesForAI = selectedCourseForAI?.syllabus ?? [];
            const moduleName = modulesForAI.find(m => m.id === syllabusModule)?.name ?? "";
            const unitName = units.find(u => u.id === topicUnit)?.name ?? "";
            const industryLabel = INDUSTRIAS_OPTIONS.find(i => i.value === industry)?.label ?? industry;

            const data = await api.suggest(intent, {
                subject: selectedCourseForAI?.name ?? "",
                academicLevel: selectedCourseForAI?.level ?? "",
                targetGroups,
                syllabusModule: moduleName,
                topicUnit: unitName,
                industry: industryLabel,
                studentProfile,
                caseType,
                edaDepth,
                includePythonCode,
                scenarioDescription,
                guidingQuestion
            });

            if (isScenario) {
                if (data.scenarioDescription) setScenarioDescription(data.scenarioDescription);
                if (data.guidingQuestion) setGuidingQuestion(data.guidingQuestion);
            }
            if (isTechniques && data.suggestedTechniques.length > 0) {
                setSuggestedTechniques(data.suggestedTechniques);
                setAreTechniquesStale(false);
            }

        } catch (err: unknown) {
            setSuggestError(err instanceof Error ? err.message : "Error generando sugerencia.");
        } finally {
            if (isScenario) setIsSuggestingScenario(false);
            if (isTechniques) setIsSuggestingTechniques(false);
        }
    };

    // ── B6: Cascading resets ──
    const handleSubjectChange = (id: string) => {
        setSubject(id);
        setSyllabusModule("");
        setTopicUnit("");
        setTargetGroups([]);
        setErrors((prev) => ({ ...prev, asignatura: false }));
    };

    const handleSyllabusModuleChange = (id: string) => {
        setSyllabusModule(id);
        setTopicUnit("");
    };

    // ── Group toggle ──
    const toggleGroup = (group: string) => {
        setTargetGroups((prev) => {
            return prev.includes(group)
                ? prev.filter((g) => g !== group)
                : [...prev, group];
        });
    };

    // ── Chips Orchestration ──
    const addChip = useCallback(
        (value: string) => {
            const trimmed = value.trim();
            if (!trimmed) return;
            if (suggestedTechniques.length >= 5) return;
            if (suggestedTechniques.some((c) => c.toLowerCase() === trimmed.toLowerCase())) return;
            setSuggestedTechniques((prev) => [...prev, trimmed]);
        },
        [suggestedTechniques]
    );

    const removeChip = useCallback((label: string) => {
        setSuggestedTechniques((prev) => prev.filter((c) => c !== label));
    }, []);

    const handleAlgoKeyDown = useCallback(
        (e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addChip(algoInput);
                setAlgoInput("");
            }
        },
        [algoInput, addChip]
    );

    // ── Component Events Triggering Warning ──
    const onChangeScenarioDescription = (val: string) => {
        setScenarioDescription(val);
        markStale();
    };
    const onChangeGuidingQuestion = (val: string) => {
        setGuidingQuestion(val);
        markStale();
    };
    const onIndustryChange = (val: string) => {
        setIndustry(val);
        markStale();
    };
    const onStudentProfileChange = (val: string) => {
        setStudentProfile(val as StudentProfile);
        markStale();
    };
    const onCaseTypeChange = (val: CaseType) => {
        setCaseType(val);
        markStale();
    };
    // ── Submit ──
    const handleSubmit = useCallback(
        (e: FormEvent) => {
            e.preventDefault();
            const newErrors: Record<string, boolean> = {};
            if (!subject) newErrors.asignatura = true;
            if (!syllabusModule) newErrors.modulo = true;
            if (targetGroups.length === 0) newErrors.targetGroups = true;
            if (!industry) newErrors.industria = true;
            if (!scenarioDescription.trim()) newErrors.scenario = true;
            if (!guidingQuestion.trim()) newErrors.guidingQuestion = true;
            // edaDepth is calculated automatically — no user validation needed

            // Validate dates implicitly relying on logical flow, highlight if reversed
            if (availableFrom && dueAt && new Date(dueAt) < new Date(availableFrom)) {
                newErrors.dateOrder = true;
                setSuggestError("La Fecha de Cierre no puede ser anterior a la Disponibilidad.");
            }

            if (Object.keys(newErrors).length > 0) {
                setErrors(newErrors);
                // Scroll simple check if date error
                const firstId = Object.keys(newErrors)[0];
                if (firstId === "dateOrder") {
                    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
                }
                return;
            }

            const courseName = selectedCourse?.name ?? "";
            const moduleName = modules.find((m) => m.id === syllabusModule)?.name ?? "";
            const unitName = units.find(u => u.id === topicUnit)?.name ?? "";
            const industryLabel = INDUSTRIAS_OPTIONS.find((i) => i.value === industry)?.label ?? industry;

            const formData: CaseFormData = {
                subject: courseName,
                academicLevel: academicLevel,
                targetGroups: targetGroups,
                syllabusModule: moduleName,
                topicUnit: unitName,
                industry: industryLabel,
                studentProfile,
                caseType,
                edaDepth,
                includePythonCode,
                scenarioDescription,
                guidingQuestion,
                suggestedTechniques,
                availableFrom,
                dueAt
            };

            onSubmit(formData);
        },
        [subject, syllabusModule, selectedCourse, modules, units, topicUnit, targetGroups, academicLevel, industry, studentProfile, caseType, edaDepth, includePythonCode, scenarioDescription, guidingQuestion, suggestedTechniques, availableFrom, dueAt, onSubmit]
    );

    // ── Clear ──
    const clearForm = () => {
        setSubject("");
        setSyllabusModule("");
        setTopicUnit("");
        setIndustry("fintech");
        setStudentProfile("business");
        setTargetGroups([]);
        setScenarioDescription("");
        setGuidingQuestion("");
        setSuggestedTechniques([]);
        setAlgoInput("");
        setErrors({});
        setIsSuggestingScenario(false);
        setIsSuggestingTechniques(false);
        setSuggestError(null);
        setAreTechniquesStale(false);
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
                        {/* ── Header ── */}
                        <div className="px-8 pt-7 pb-6" style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)" }}>
                            <div className="flex items-center gap-3.5">
                                <div className="flex-shrink-0 h-10 w-10 rounded-xl bg-white/20 flex items-center justify-center text-white">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                                    </svg>
                                </div>
                                <div>
                                    <h1 className="text-lg font-bold text-white leading-tight tracking-tight">Diseñador de Casos ADAM</h1>
                                    <p className="text-sm text-blue-200 mt-0.5">Configure los parámetros pedagógicos para generar el caso.</p>
                                </div>
                            </div>
                        </div>

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
                                                        {professorDB.courses.map((c) => (
                                                            <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.asignatura} />
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
                                        <label className="block text-sm font-semibold text-slate-700 mb-2">
                                            Grupos Destino <span className="text-red-500" aria-hidden="true">*</span>
                                        </label>
                                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
                                            {selectedCourse ? (
                                                selectedCourse.activeGroups.map((grp) => (
                                                    <label key={grp} className="flex items-center gap-2 cursor-pointer bg-white border border-slate-200 rounded px-3 py-2 hover:border-blue-300 transition-colors">
                                                        <input
                                                            type="checkbox"
                                                            checked={targetGroups.includes(grp)}
                                                            onChange={() => toggleGroup(grp)}
                                                            className="w-4 h-4 text-[#0144a0] border-slate-300 rounded focus:ring-[#0144a0]"
                                                        />
                                                        <span className="text-sm text-slate-700 font-medium">{grp}</span>
                                                    </label>
                                                ))
                                            ) : (
                                                <span className="text-sm text-slate-400 col-span-full py-1">
                                                </span>
                                            )}
                                        </div>
                                        {errors.targetGroups && <ErrorMsg show={true} />}
                                        <p className="field-hint">Seleccione uno o más grupos para asignar este caso simultáneamente.</p>
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
                                                            <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
                                            <ErrorMsg show={!!errors.modulo} />
                                        </div>

                                        <div>
                                            <label htmlFor="field-unidad" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Unidad Temática <span className="text-xs font-normal text-slate-400 ml-1">(Opcional, mayor precisión)</span>
                                            </label>
                                            <Select
                                                disabled={!syllabusModule}
                                                value={topicUnit}
                                                onValueChange={setTopicUnit}
                                            >
                                                <SelectTrigger
                                                    id="field-unidad"
                                                    className="input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 disabled:bg-slate-50 disabled:text-slate-400"
                                                >
                                                    <SelectValue placeholder={syllabusModule ? "Todas las unidades (General)" : "Seleccione módulo primero..."} />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    <SelectGroup>
                                                        {units.map((u) => (
                                                            <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
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
                                                        {STUDENT_PROFILES.map((opt) => (
                                                            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                                                        ))}
                                                    </SelectGroup>
                                                </SelectContent>
                                            </Select>
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

                                    {/* Notebook toggle — only for ml_ds + harvard_with_eda */}
                                    {caseType === "harvard_with_eda" && studentProfile === "ml_ds" && (
                                        <div className="p-4 border border-blue-100 bg-blue-50/30 rounded-xl">
                                            <label className="flex items-center gap-3 cursor-pointer select-none">
                                                <button
                                                    type="button"
                                                    role="switch"
                                                    aria-checked={notebookToggle}
                                                    onClick={() => setNotebookToggle((prev) => !prev)}
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

                                    {/* Sugestión global error flag */}
                                    {suggestError && (
                                        <div className="p-3 mb-2 rounded border border-red-200 bg-red-50 text-red-600 text-[13px] font-medium flex items-center gap-2">
                                            <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12A9 9 0 113 12a9 9 0 0118 0z" />
                                            </svg>
                                            {suggestError}
                                        </div>
                                    )}

                                    {/* Descripción y Pregunta Guía */}
                                    <div className="space-y-4 pt-1">
                                        <div>
                                            <label htmlFor="field-scenarioDescription" className="block text-sm font-semibold text-slate-700 mb-1.5">
                                                Descripción del Escenario (Obligatorio) <span className="text-red-500" aria-hidden="true">*</span>
                                                <button
                                                    type="button"
                                                    onClick={() => fetchSuggestion('scenario')}
                                                    disabled={!canSuggest}
                                                    className={`ml-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-bold text-[#0144a0] bg-blue-50 border border-blue-200 rounded-lg transition-all ${!canSuggest ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-blue-100 hover:border-blue-300 hover:shadow-sm active:scale-[0.97]"}`}
                                                >
                                                    {isSuggestingScenario ? (
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

                                    {/* Técnicas / Algoritmos — visible for harvard_with_eda or for ml_ds with any case type */}
                                    {(caseType === "harvard_with_eda" || studentProfile === "ml_ds") && (
                                        <div className="pt-4 border-t border-slate-100 mt-2">
                                            <div className="flex items-center justify-between mb-2.5">
                                                <div>
                                                    <label className="text-sm font-semibold text-slate-700 block" htmlFor="algo-input">
                                                        Algoritmos / Técnicas Sugeridas
                                                        <button
                                                            type="button"
                                                            onClick={() => fetchSuggestion('techniques')}
                                                            disabled={!canSuggest}
                                                            className={`ml-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-bold text-[#0144a0] bg-blue-50 border border-blue-200 rounded-lg transition-all ${!canSuggest ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-blue-100 hover:border-blue-300 hover:shadow-sm active:scale-[0.97]"}`}
                                                        >
                                                            {isSuggestingTechniques ? (
                                                                <><span className="animate-spin w-3 h-3 border-2 border-[#0144a0] border-t-transparent rounded-full"></span> Pensando...</>
                                                            ) : (
                                                                <>🪄 Sugerir Técnicas de Análisis</>
                                                            )}
                                                        </button>
                                                    </label>
                                                    <span className="text-xs text-slate-400 font-normal">
                                                        {caseType === "harvard_only"
                                                            ? "Opcional — sin datos adjuntos en este modo. Sirven como contexto pedagógico del perfil ML/DS."
                                                            : "Si las dejas vacías, ADAM sugerirá las técnicas más adecuadas según el contexto del caso. Máx. 5"}
                                                    </span>
                                                </div>

                                            </div>

                                            <div
                                                onClick={() => document.getElementById("algo-input")?.focus()}
                                                className={`input-base w-full flex flex-wrap items-center gap-2 rounded-lg border bg-white px-3 py-2 min-h-[46px] cursor-text transition-colors duration-300 ${areTechniquesStale ? 'border-amber-300 bg-amber-50/20' : 'border-slate-200'}`}
                                            >
                                                {suggestedTechniques.map((chip) => (
                                                    <span
                                                        key={chip}
                                                        className={`chip inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-semibold ${areTechniquesStale ? 'border-amber-200 bg-amber-100/50 text-amber-800' : 'border-blue-200 bg-blue-50 text-[#0144a0]'}`}
                                                    >
                                                        {chip}
                                                        <button
                                                            type="button"
                                                            onClick={(e) => { e.stopPropagation(); removeChip(chip); }}
                                                            className={`focus:outline-none ml-1 leading-none text-base ${areTechniquesStale ? 'text-amber-500 hover:text-amber-700' : 'text-blue-400 hover:text-red-500'}`}
                                                        >
                                                            ×
                                                        </button>
                                                    </span>
                                                ))}
                                                <input
                                                    id="algo-input"
                                                    type="text"
                                                    value={algoInput}
                                                    onChange={(e) => setAlgoInput(e.target.value)}
                                                    onKeyDown={handleAlgoKeyDown}
                                                    placeholder="Escribir nombre técnico y Enter..."
                                                    className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400 min-w-[200px] py-0.5"
                                                />
                                            </div>
                                            {suggestedTechniques.length >= 5 && (
                                                <div className="chip-warning">Máximo 5 algoritmos permitidos.</div>
                                            )}
                                            {areTechniquesStale && suggestedTechniques.length > 0 && (
                                                <div className="text-[11.5px] font-medium text-amber-700 mt-2 ml-1 animate-pulse">
                                                    ⚠️ Las técnicas sugeridas podrían estar desactualizadas de acuerdo al último contexto académico configurado.
                                                </div>
                                            )}
                                            <p className="field-hint mt-1.5">ADAM optimizará estas variables sobre el Dataset ficticio si logras predefinirlas.</p>
                                        </div>
                                    )}
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
                                            onChange={(e) => setAvailableFrom(e.target.value)}
                                            className="input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 cursor-pointer"
                                        />
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
                                            onChange={(e) => setDueAt(e.target.value)}
                                            className="input-base w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 cursor-pointer"
                                        />
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
                                        className="flex items-center gap-2 rounded-xl bg-[#0144a0] px-7 py-2.5 text-sm font-bold text-white shadow-md transition-all hover:bg-[#00337a] hover:shadow-lg active:scale-[0.98]"
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

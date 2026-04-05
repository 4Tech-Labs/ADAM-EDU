import type { Data, Layout } from "plotly.js";

/** Core TypeScript contracts for the teacher authoring and preview MVP. */

// Chart specs for the current EDA preview pipeline.
export interface EDAChartSpec {
    id: string;
    title?: string;
    subtitle?: string;
    description?: string;
    chart_type?: string;
    traces: Data[];
    layout: Partial<Layout>;
    library?: string;
    source?: string;
    notes?: string;
    academic_rationale?: string;
}

// Question contracts rendered in the current teacher preview.
export interface PreguntaMinimalista {
    numero: number;
    titulo: string;
    enunciado: string;
    solucion_esperada?: string;      // optional: stripped from m5Questions in student-facing payload
    bloom_level?: string;           // e.g. "analysis" | "evaluation" | "synthesis"
    m3_section_ref?: string;        // sección M3 que fundamenta la pregunta (e.g. "3.2")
    m4_section_ref?: string;        // sección M4 que fundamenta la pregunta
    modules_integrated?: string[];  // módulos integrados en preguntas M5
    is_solucion_docente_only?: boolean; // M5: siempre true — solucion_esperada filtrada del payload al estudiante
}

// Teacher-only M5 solutions kept separate from the student-facing payload.
// Generadas por m5_questions_generator, filtradas en frontend_output_adapter.
// El frontend las fusiona con m5Questions para la vista docente.
export interface M5QuestionSolution {
    numero: number;
    solucion_esperada: string;  // respuesta modelo completa de 4 párrafos (250-300 palabras)
}

// Module 2 EDA questions use a richer structured answer schema.
export interface EDASolucionEsperada {
    teoria: string;
    ejemplo: string;
    implicacion: string;
    literatura: string;
}

export interface EDASocraticQuestion {
    numero: number;
    titulo: string;
    enunciado: string;
    solucion_esperada: EDASolucionEsperada;
    bloom_level?: string;
    chart_ref?: string;
    exhibit_ref?: string;
    task_type: "text_response" | "notebook_task";
}

export type CaseType = "harvard_only" | "harvard_with_eda";
export type EDADepth = "charts_only" | "charts_plus_explanation" | "charts_plus_code";
export type IntentType = "scenario" | "techniques" | "both";
export type StudentProfile = "business" | "ml_ds";
export type ModuleId = "m1" | "m2" | "m3" | "m4" | "m5" | "m6";
export interface CaseFormData {
    subject: string;
    academicLevel: string;
    targetGroups: string[];
    syllabusModule: string;
    topicUnit: string;
    industry: string;
    studentProfile: StudentProfile;
    caseType: CaseType;
    edaDepth?: EDADepth;
    includePythonCode: boolean;
    scenarioDescription: string;
    guidingQuestion: string;
    suggestedTechniques: string[];
    // Submission / Delivery
    availableFrom: string;
    dueAt: string;
}

// Canonical output contract consumed by the current preview.
export interface CaseContent {
    instructions?: string;
    narrative?: string;
    financialExhibit?: string;
    operatingExhibit?: string;
    stakeholdersExhibit?: string;
    caseQuestions?: PreguntaMinimalista[];
    edaReport?: string;
    edaCharts?: EDAChartSpec[];
    edaQuestions?: (PreguntaMinimalista | EDASocraticQuestion)[];  // v9 M2-Redesign: union type
    teachingNote?: string;

    // ── v5.0: nuevos documentos ──
    /** @deprecated doc6 obsoleto — M2 ya no genera notebook. Solo presente en datos históricos. */
    notebookCode?: string;
    datasetRows?: Record<string, unknown>[];     // doc7 — filas del dataset sintético
    doc7Dataset?: Record<string, unknown>[];     // alias / corrección pedida en plan v8

    // ── v7: preguntas de módulos de impacto y recomendación ──
    m4Questions?: PreguntaMinimalista[];         // generadas por m4_questions_generator
    m5Questions?: PreguntaMinimalista[];         // generadas por m5_questions_generator (solucion_esperada ausente — filtrada)
    m5QuestionsSolutions?: M5QuestionSolution[]; // docente-only: solucion_esperada de M5 (4 párrafos, 250-300 palabras)

    // ── v8: contenido adicional de módulos ──
    m3Content?: string;
    m3Charts?: EDAChartSpec[];
    m3Questions?: PreguntaMinimalista[];
    m3NotebookCode?: string;                     // Jupytext Percent — Experiment Engineer (ml_ds + visual_plus_notebook)
    m4Content?: string;
    m4Charts?: EDAChartSpec[];
    m5Content?: string;
}

export interface CanonicalCaseOutput {
    caseId?: string;
    title: string;
    subject: string;
    syllabusModule: string;
    guidingQuestion: string;
    industry: string;
    academicLevel: string;
    caseType: CaseType;
    // Optional so older jobs can still render with safe preview fallbacks.
    edaDepth?: EDADepth;
    studentProfile?: StudentProfile;
    generatedAt: string;
    content: CaseContent; // Optional properties inside allow for partial state during HITL

    // Adaptive preview metadata preserved for the current rendering contract.
    /** "visual_plus_technical" | "visual_plus_notebook" | null */
    outputDepth?: string;
}

export interface AuthoringJobCreateRequest {
    assignment_title: string;
    subject: string;
    academic_level: string;
    industry: string;
    student_profile: StudentProfile;
    case_type: CaseType;
    syllabus_module: string;
    scenario_description: string;
    guiding_question: string;
    topic_unit: string;
    target_groups: string[];
    eda_depth: EDADepth | null;
    include_python_code: boolean;
    suggested_techniques: string[];
    available_from: string | null;
    due_at: string | null;
}

export interface AuthoringJobCreateResponse {
    job_id: string;
    [key: string]: unknown;
}

export interface SuggestRequest {
    subject: string;
    academicLevel: string;
    targetGroups: string[];
    syllabusModule: string;
    topicUnit: string;
    industry: string;
    studentProfile: StudentProfile;
    caseType: CaseType;
    edaDepth?: EDADepth;
    includePythonCode: boolean;
    scenarioDescription: string;
    guidingQuestion: string;
}

export interface SuggestResponse {
    scenarioDescription?: string;
    guidingQuestion?: string;
    suggestedTechniques: string[];
    [key: string]: unknown;
}


// API responses used by the teacher authoring flow.
export type AuthoringJobStatus = "pending" | "processing" | "completed" | "failed";

export interface AuthoringJobStatusResponse {
    job_id: string;
    status: AuthoringJobStatus;
    assignment_id: string;
    created_at: string;
    updated_at: string;
    error_trace?: string;
}

export interface AuthoringJobResultResponse {
    job_id: string;
    assignment_id: string;
    blueprint: Record<string, unknown> & {
        config_object?: Record<string, unknown>;
        student_artifacts?: Record<string, unknown>;
    };
    canonical_output?: CanonicalCaseOutput;    // v5.0 — Option D
}

export type AppState = "idle" | "generating" | "success" | "editing" | "error";

export type NivelAcademico = string;

export const NIVELES: NivelAcademico[] = [
    "Pregrado",
    "Especialización",
    "Maestría",
    "MBA",
    "Doctorado",
];

export const INDUSTRIAS = [
    "FinTech",
    "Retail",
    "Salud",
    "Educación",
    "Logística",
    "Telecomunicaciones",
    "Manufactura",
    "Banca",
    "Seguros",
    "Turismo",
];

// Invite and activation API contracts — Issue #37 / #39
export interface InviteResolveResponse {
    role: "teacher" | "student";
    email_masked: string;
    university_name: string;
    course_title: string | null;
    teacher_name: string | null;
    status: "pending" | "expired" | "consumed" | "revoked";
    expires_at: string;
}

export interface InviteRedeemResponse {
    // "redeemed" = first time; "already_enrolled" = idempotent re-join
    status: "redeemed" | "already_enrolled";
}

export interface ActivatePasswordRequest {
    invite_token: string;
    password: string;
    confirm_password: string;
    full_name?: string;
}

export interface ActivatePasswordResponse {
    status: string;
    next_step: string;
    email: string;
}

export interface ActivateOAuthCompleteResponse {
    status: string;
}

// Admin password rotation (Issue #8)
export interface ChangePasswordRequest {
    new_password: string;
}

export interface ChangePasswordResponse {
    status: string;
}

export const EMPTY_FORM: CaseFormData = {
    subject: "",
    academicLevel: "Pregrado",
    targetGroups: [],
    syllabusModule: "",
    topicUnit: "",
    industry: "FinTech",
    studentProfile: "business",
    caseType: "harvard_only",
    includePythonCode: false,
    scenarioDescription: "",
    guidingQuestion: "",
    suggestedTechniques: [],
    availableFrom: "",
    dueAt: "",
};

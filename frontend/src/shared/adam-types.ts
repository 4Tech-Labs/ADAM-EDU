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
    courseId: string;
    subject: string;
    academicLevel: string;
    targetGroups: string[];
    targetCourseIds: string[];
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
    course_id: string;
    target_course_ids: string[];
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
export type AuthoringJobStatus =
    | "pending"
    | "processing"
    | "completed"
    | "failed"
    | "failed_resumable";

export const AUTHORING_PROGRESS_STEP_IDS = [
    "case_architect",
    "case_writer",
    "eda_text_analyst",
    "m3_content_generator",
    "m4_content_generator",
    "m5_content_generator",
    "teaching_note_part1",
] as const;

export type AuthoringProgressStep = (typeof AUTHORING_PROGRESS_STEP_IDS)[number];
export type AuthoringProgressCheckpoint = AuthoringProgressStep | "completed" | "failed";
export type AuthoringBootstrapState = "initializing";

export interface AuthoringJobStatusResponse {
    job_id: string;
    status: AuthoringJobStatus;
    assignment_id: string;
    created_at: string;
    updated_at: string;
    error_trace?: string;
}

export interface AuthoringJobProgressSnapshotResponse {
    job_id: string;
    status: AuthoringJobStatus;
    current_step?: AuthoringProgressCheckpoint;
    progress_percentage?: number;
    bootstrap_state?: AuthoringBootstrapState;
    progress_seq?: number;
    progress_ts?: string;
    error_code?: string;
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

export interface AuthoringJobRetryResponse {
    job_id: string;
    status: "accepted";
    message: string;
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

export type AllowedAuthMethod = "password" | "microsoft";

export type ActivationContext =
    | {
        flow: "teacher_activate";
        token_kind: "invite";
        invite_token: string;
        role: "teacher";
        expires_at: number;
    }
    | {
        flow: "student_join_invite";
        token_kind: "invite";
        invite_token: string;
        role: "student";
        expires_at: number;
    }
    | {
        flow: "student_join_course_access";
        token_kind: "course_access";
        course_access_token: string;
        auth_path?: "oauth" | "password_sign_in";
        expires_at: number;
    };

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

export interface CourseAccessResolveResponse {
    course_id: string;
    course_title: string;
    university_name: string;
    teacher_display_name: string | null;
    course_status: "active";
    link_status: "active";
    allowed_auth_methods: AllowedAuthMethod[];
}

export interface CourseAccessEnrollResponse {
    status: "enrolled" | "already_enrolled";
}

export interface CourseAccessActivatePasswordRequest {
    course_access_token: string;
    email?: string;
    full_name?: string;
    password: string;
    confirm_password: string;
}

export interface CourseAccessActivatePasswordResponse {
    status: "activated";
    next_step: "sign_in";
    email: string;
}

export interface CourseAccessActivateCompleteResponse {
    status: "activated";
}

export interface CourseAccessActivateOAuthCompleteResponse {
    status: "activated";
}

// Admin password rotation (Issue #8)
export interface ChangePasswordRequest {
    new_password: string;
}

export interface ChangePasswordResponse {
    status: string;
}

export type StudentCourseStatus = "active" | "inactive";
export type StudentCaseStatus = "available" | "in_progress" | "submitted" | "upcoming" | "closed";
export type StudentCaseDraftStatus = "draft" | "submitted";

export interface StudentCourseItem {
    id: string;
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    status: StudentCourseStatus;
    teacher_display_name: string;
    pending_cases_count: number;
    next_case_title: string | null;
    next_deadline: string | null;
}

export interface StudentCoursesResponse {
    courses: StudentCourseItem[];
    total: number;
}

export interface StudentCaseItem {
    id: string;
    title: string;
    available_from: string | null;
    deadline: string | null;
    status: StudentCaseStatus;
    course_codes: string[];
}

export interface StudentCasesResponse {
    cases: StudentCaseItem[];
    total: number;
}

export interface StudentCaseAssignmentMeta {
    id: string;
    title: string;
    available_from: string | null;
    deadline: string | null;
    status: StudentCaseStatus;
    course_codes: string[];
}

export interface StudentCaseResponseState {
    status: StudentCaseDraftStatus;
    answers: Record<string, string>;
    version: number;
    last_autosaved_at: string | null;
    submitted_at: string | null;
}

export interface StudentCaseDetailResponse {
    assignment: StudentCaseAssignmentMeta;
    canonical_output: CanonicalCaseOutput;
    response: StudentCaseResponseState;
}

export interface StudentCaseDraftRequest {
    answers: Record<string, string>;
    version: number;
}

export interface StudentCaseDraftResponse {
    version: number;
    last_autosaved_at: string;
}

export interface StudentCaseSubmitRequest {
    answers: Record<string, string>;
    version: number;
}

export interface StudentCaseSubmitResponse {
    status: "submitted";
    submitted_at: string;
    version: number;
}

export interface AdminDashboardSummaryResponse {
    active_courses: number;
    active_teachers: number;
    enrolled_students: number;
    average_occupancy: number;
}

export interface AdminTeacherMembershipAssignment {
    kind: "membership";
    membership_id: string;
}

export interface AdminTeacherPendingInviteAssignment {
    kind: "pending_invite";
    invite_id: string;
}

export type AdminTeacherAssignment =
    | AdminTeacherMembershipAssignment
    | AdminTeacherPendingInviteAssignment;

export type AdminTeacherState = "active" | "pending" | "stale_pending_invite" | "unassigned";
export type AdminCourseStatus = "active" | "inactive";
export type AdminCourseAccessLinkStatus = "active" | "missing";

export interface AdminCourseListItem {
    id: string;
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    status: AdminCourseStatus;
    teacher_display_name: string;
    teacher_state: AdminTeacherState;
    teacher_assignment: AdminTeacherAssignment | null;
    students_count: number;
    max_students: number;
    occupancy_percent: number;
    access_link: string | null;
    access_link_status: AdminCourseAccessLinkStatus;
}

export interface AdminCourseListResponse {
    items: AdminCourseListItem[];
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
}

export interface AdminTeacherOption {
    membership_id: string;
    full_name: string;
    email: string;
}

export interface AdminPendingTeacherInviteOption {
    invite_id: string;
    full_name: string;
    email: string;
    status: "pending";
}

export interface AdminTeacherOptionsResponse {
    active_teachers: AdminTeacherOption[];
    pending_invites: AdminPendingTeacherInviteOption[];
}

export interface AdminCourseMutationRequest {
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    max_students: number;
    status: AdminCourseStatus;
    teacher_assignment: AdminTeacherAssignment;
}

export interface AdminTeacherInviteRequest {
    full_name: string;
    email: string;
}

export interface AdminTeacherInviteResponse {
    invite_id: string;
    full_name: string;
    email: string;
    status: "pending";
    activation_link: string;
}

export interface CourseAccessLinkRegenerateResponse {
    course_id: string;
    access_link: string;
    access_link_status: "active";
}

export type AdminCourseAccessLinkRegenerateResponse = CourseAccessLinkRegenerateResponse;

export interface AdminCourseRef {
    course_id: string;
    title: string;
    code: string;
    semester: string;
    status: AdminCourseStatus;
}

export interface AdminTeacherDirectoryEntry {
    membership_id: string;
    full_name: string;
    email: string;
    assigned_courses: AdminCourseRef[];
}

export interface AdminTeacherDirectoryInvite {
    invite_id: string;
    full_name: string;
    email: string;
    status: "pending";
    expires_at: string;
    assigned_courses: AdminCourseRef[];
}

export interface AdminTeacherDirectoryResponse {
    active_teachers: AdminTeacherDirectoryEntry[];
    pending_invites: AdminTeacherDirectoryInvite[];
}

export interface AdminRemoveTeacherResponse {
    removed_membership_id: string;
    affected_course_ids: string[];
}

export interface AdminRevokeInviteResponse {
    revoked_invite_id: string;
    affected_course_ids: string[];
}

export interface AdminResendInviteResponse {
    invite_id: string;
    activation_link: string;
    expires_at: string;
}

export type TeacherCourseStatus = "active" | "inactive";

export interface TeacherCourseItem {
    id: string;
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    status: TeacherCourseStatus;
    students_count: number;
    active_cases_count: number;
}

export interface TeacherCoursesResponse {
    courses: TeacherCourseItem[];
    total: number;
}

export interface TeacherSyllabusUnit {
    unit_id: string;
    title: string;
    topics: string;
}

export interface TeacherSyllabusModule {
    module_id: string;
    module_title: string;
    weeks: string;
    module_summary: string;
    learning_outcomes: string[];
    units: TeacherSyllabusUnit[];
    cross_course_connections: string;
}

export interface TeacherEvaluationStrategyItem {
    activity: string;
    weight: number;
    linked_objectives: string[];
    expected_outcome: string;
}

export interface TeacherDidacticStrategy {
    methodological_perspective: string;
    pedagogical_modality: string;
}

export interface TeacherSyllabusPayload {
    department: string;
    knowledge_area: string;
    nbc: string;
    version_label: string;
    academic_load: string;
    course_description: string;
    general_objective: string;
    specific_objectives: string[];
    modules: TeacherSyllabusModule[];
    evaluation_strategy: TeacherEvaluationStrategyItem[];
    didactic_strategy: TeacherDidacticStrategy;
    integrative_project: string;
    bibliography: string[];
    teacher_notes: string;
}

export interface TeacherSyllabusGroundingCourseIdentity {
    course_id: string;
    course_title: string;
    academic_level: string;
    department: string;
    knowledge_area: string;
    nbc: string;
}

export interface TeacherSyllabusGroundingPedagogicalIntent {
    course_description: string;
    general_objective: string;
    specific_objectives: string[];
}

export interface TeacherSyllabusGroundingInstructionalScope {
    modules: TeacherSyllabusModule[];
    evaluation_strategy: TeacherEvaluationStrategyItem[];
    didactic_strategy: TeacherDidacticStrategy;
}

export interface TeacherSyllabusGroundingGenerationHints {
    target_student_profile: string;
    scenario_constraints: string[];
    preferred_techniques: string[];
    difficulty_signal: string;
    forbidden_mismatches: string[];
}

export interface TeacherSyllabusGroundingMetadata {
    syllabus_revision: number;
    saved_at: string;
    saved_by_membership_id: string;
}

export interface TeacherSyllabusGroundingContext {
    course_identity: TeacherSyllabusGroundingCourseIdentity;
    pedagogical_intent: TeacherSyllabusGroundingPedagogicalIntent;
    instructional_scope: TeacherSyllabusGroundingInstructionalScope;
    generation_hints: TeacherSyllabusGroundingGenerationHints;
    metadata: TeacherSyllabusGroundingMetadata;
}

export interface TeacherSyllabusResponse extends TeacherSyllabusPayload {
    ai_grounding_context: TeacherSyllabusGroundingContext;
}

export interface TeacherSyllabusRevisionMetadata {
    current_revision: number;
    saved_at: string | null;
    saved_by_membership_id: string | null;
}

export type TeacherCourseAccessLinkStatus = "active" | "missing";

export interface TeacherCourseInstitutionalDetail {
    id: string;
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    status: TeacherCourseStatus;
    max_students: number;
    students_count: number;
    active_cases_count: number;
}

export interface TeacherCourseConfiguration {
    access_link_status: TeacherCourseAccessLinkStatus;
    access_link_id: string | null;
    access_link_created_at: string | null;
    join_path: string;
}

export interface TeacherCourseAccessLinkResponse extends TeacherCourseConfiguration {
    course_id: string;
}

export type TeacherCourseAccessLinkRegenerateResponse = CourseAccessLinkRegenerateResponse;

export interface TeacherCourseDetailResponse {
    course: TeacherCourseInstitutionalDetail;
    syllabus: TeacherSyllabusResponse | null;
    revision_metadata: TeacherSyllabusRevisionMetadata;
    configuration: TeacherCourseConfiguration;
}

export type TeacherCourseGradebookStatus =
    | "not_started"
    | "in_progress"
    | "submitted"
    | "graded";

export interface TeacherCourseGradebookCourse {
    id: string;
    title: string;
    code: string;
    students_count: number;
    cases_count: number;
    average_score_scale: number;
}

export interface TeacherCourseGradebookCase {
    assignment_id: string;
    title: string;
    status: "published";
    available_from: string | null;
    deadline: string | null;
    max_score: number;
}

export interface TeacherCourseGradebookCell {
    assignment_id: string;
    status: TeacherCourseGradebookStatus;
    score: number | null;
    graded_at: string | null;
}

export interface TeacherCourseGradebookStudent {
    membership_id: string;
    full_name: string;
    email: string;
    enrolled_at: string;
    average_score: number | null;
    grades: TeacherCourseGradebookCell[];
}

export interface TeacherCourseGradebookResponse {
    course: TeacherCourseGradebookCourse;
    cases: TeacherCourseGradebookCase[];
    students: TeacherCourseGradebookStudent[];
}

export interface TeacherSyllabusSaveRequest {
    expected_revision: number;
    syllabus: TeacherSyllabusPayload;
}

export interface TeacherCaseItem {
    id: string;
    title: string;
    available_from?: string | null;
    deadline: string | null;
    status: string;
    course_codes: string[];
    days_remaining: number | null;
}

export interface TeacherCasesResponse {
    cases: TeacherCaseItem[];
    total: number;
}

export interface TeacherCaseDetailResponse {
    id: string;
    title: string;
    status: string;
    available_from: string | null;
    deadline: string | null;
    course_id: string | null;
    target_course_ids?: string[];
    course_codes?: string[];
    canonical_output: CanonicalCaseOutput | null;
}

export interface TeacherCaseSubmissionRow {
    membership_id: string;
    full_name: string;
    email: string;
    course_id: string;
    course_code: string;
    enrolled_at: string;
    status: TeacherCourseGradebookStatus;
    submitted_at: string | null;
    score: number | null;
    max_score: number;
    graded_at: string | null;
}

export interface TeacherCaseSubmissionsResponse {
    case: TeacherCourseGradebookCase;
    submissions: TeacherCaseSubmissionRow[];
}

export interface TeacherCaseSubmissionDetailQuestion {
    id: string;
    order: number;
    statement: string;
    context: string | null;
    expected_solution: string;
    student_answer: string | null;
    student_answer_chars: number;
    is_answer_from_draft: boolean;
}

export interface TeacherCaseSubmissionDetailModule {
    id: "M1" | "M2" | "M3" | "M4" | "M5";
    title: string;
    questions: TeacherCaseSubmissionDetailQuestion[];
}

export interface TeacherCaseSubmissionDetailCase {
    id: string;
    title: string;
    deadline: string | null;
    available_from: string | null;
    course_id: string;
    course_code: string;
    course_name: string;
    teaching_note: string | null;
}

export interface TeacherCaseSubmissionDetailStudent {
    membership_id: string;
    full_name: string;
    email: string;
    enrolled_at: string;
}

export interface TeacherCaseSubmissionDetailResponseState {
    status: TeacherCourseGradebookStatus;
    first_opened_at: string | null;
    last_autosaved_at: string | null;
    submitted_at: string | null;
    snapshot_id: string | null;
    snapshot_hash: string | null;
}

export interface TeacherCaseSubmissionDetailGradeSummary {
    status: "in_progress" | "submitted" | "graded" | null;
    score: number | null;
    max_score: number;
    graded_at: string | null;
}

export interface TeacherCaseSubmissionDetailResponse {
    payload_version: 1;
    is_truncated: boolean;
    case: TeacherCaseSubmissionDetailCase;
    case_view?: CanonicalCaseOutput | null;
    student: TeacherCaseSubmissionDetailStudent;
    response_state: TeacherCaseSubmissionDetailResponseState;
    grade_summary: TeacherCaseSubmissionDetailGradeSummary;
    modules: TeacherCaseSubmissionDetailModule[];
}

export interface DeadlineUpdateRequest {
    available_from?: string | null;
    deadline?: string | null;
}

export const EMPTY_FORM: CaseFormData = {
    courseId: "",
    subject: "",
    academicLevel: "Pregrado",
    targetGroups: [],
    targetCourseIds: [],
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

import type {
    CaseContent,
    CaseType,
    CanonicalCaseOutput,
    EDAChartSpec,
    EDADepth,
    EDASocraticQuestion,
    EDASolucionEsperada,
    M5QuestionSolution,
    PreguntaMinimalista,
    StudentProfile,
    TeacherCaseSubmissionDetailModule,
    TeacherCaseSubmissionDetailQuestion,
    TeacherCaseSubmissionDetailResponse,
} from "@/shared/adam-types";

type QuestionLike = PreguntaMinimalista | EDASocraticQuestion;
type QuestionArray = Array<QuestionLike>;
type MinimalQuestionArray = PreguntaMinimalista[];
type ContentQuestionKey = "caseQuestions" | "edaQuestions" | "m3Questions" | "m4Questions" | "m5Questions";

const EMPTY_GENERATED_AT = new Date(0).toISOString();

const MODULE_CONTENT_KEY_BY_ID: Record<TeacherCaseSubmissionDetailModule["id"], ContentQuestionKey> = {
    M1: "caseQuestions",
    M2: "edaQuestions",
    M3: "m3Questions",
    M4: "m4Questions",
    M5: "m5Questions",
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
    return typeof value === "string" ? value : undefined;
}

function readNonBlankString(value: unknown): string | undefined {
    const text = readString(value)?.trim();
    return text ? text : undefined;
}

function readFiniteNumber(value: unknown): number | undefined {
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readStringArray(value: unknown): string[] | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const items = value.filter((item): item is string => typeof item === "string");
    return items.length > 0 ? items : undefined;
}

function isCaseType(value: unknown): value is CaseType {
    return value === "harvard_only" || value === "harvard_with_eda";
}

function isStudentProfile(value: unknown): value is StudentProfile {
    return value === "business" || value === "ml_ds";
}

function isEdaDepth(value: unknown): value is EDADepth {
    return value === "charts_only"
        || value === "charts_plus_explanation"
        || value === "charts_plus_code";
}

function sanitizeLooseRecord(value: unknown): Record<string, unknown> | null {
    if (!isRecord(value)) {
        return null;
    }

    const result: Record<string, unknown> = {};

    for (const [key, entry] of Object.entries(value)) {
        if (key === "__proto__" || key === "constructor" || key === "prototype") {
            continue;
        }

        result[key] = entry;
    }

    return result;
}

function sanitizeDatasetRows(value: unknown): Record<string, unknown>[] | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const rows = value
        .map((row) => sanitizeLooseRecord(row))
        .filter((row): row is Record<string, unknown> => row !== null);

    return rows.length > 0 ? rows : undefined;
}

function sanitizeChartSpec(value: unknown): EDAChartSpec | null {
    if (!isRecord(value)) {
        return null;
    }

    const id = readString(value.id);
    if (!id) {
        return null;
    }

    return {
        id,
        title: readString(value.title),
        subtitle: readString(value.subtitle),
        description: readString(value.description),
        chart_type: readString(value.chart_type),
        traces: Array.isArray(value.traces) ? (value.traces as EDAChartSpec["traces"]) : [],
        layout: sanitizeLooseRecord(value.layout) ?? {},
        library: readString(value.library),
        source: readString(value.source),
        notes: readString(value.notes),
        academic_rationale: readString(value.academic_rationale),
    };
}

function sanitizeChartArray(value: unknown): EDAChartSpec[] | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const charts = value
        .map((entry) => sanitizeChartSpec(entry))
        .filter((entry): entry is EDAChartSpec => entry !== null);

    return charts.length > 0 ? charts : undefined;
}

function sanitizeEdaExpectedSolution(value: unknown): EDASolucionEsperada | null {
    if (!isRecord(value)) {
        return null;
    }

    const teoria = readString(value.teoria);
    const ejemplo = readString(value.ejemplo);
    const implicacion = readString(value.implicacion);
    const literatura = readString(value.literatura);

    if (!teoria || !ejemplo || !implicacion || !literatura) {
        return null;
    }

    return {
        teoria,
        ejemplo,
        implicacion,
        literatura,
    };
}

function sanitizeMinimalQuestion(value: unknown): PreguntaMinimalista | null {
    if (!isRecord(value)) {
        return null;
    }

    const numero = readFiniteNumber(value.numero);
    const titulo = readString(value.titulo);
    const enunciado = readString(value.enunciado);

    if (numero === undefined || !titulo || !enunciado) {
        return null;
    }

    return {
        numero,
        titulo,
        enunciado,
        solucion_esperada: readString(value.solucion_esperada),
        bloom_level: readString(value.bloom_level),
        m3_section_ref: readString(value.m3_section_ref),
        m4_section_ref: readString(value.m4_section_ref),
        modules_integrated: readStringArray(value.modules_integrated),
        is_solucion_docente_only: value.is_solucion_docente_only === true ? true : undefined,
    };
}

function sanitizeMinimalQuestionArray(value: unknown): MinimalQuestionArray | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const questions = value
        .map((entry) => sanitizeMinimalQuestion(entry))
        .filter((entry): entry is PreguntaMinimalista => entry !== null);

    return questions.length > 0 ? questions : undefined;
}

function sanitizeQuestion(value: unknown): QuestionLike | null {
    if (!isRecord(value)) {
        return null;
    }

    const taskType = value.task_type;
    if (taskType === "text_response" || taskType === "notebook_task") {
        const numero = readFiniteNumber(value.numero);
        const titulo = readString(value.titulo);
        const enunciado = readString(value.enunciado);
        const solucionEsperada = sanitizeEdaExpectedSolution(value.solucion_esperada);

        if (numero !== undefined && titulo && enunciado && solucionEsperada) {
            return {
                numero,
                titulo,
                enunciado,
                solucion_esperada: solucionEsperada,
                bloom_level: readString(value.bloom_level),
                chart_ref: readString(value.chart_ref),
                exhibit_ref: readString(value.exhibit_ref),
                task_type: taskType,
            };
        }
    }

    return sanitizeMinimalQuestion(value);
}

function sanitizeQuestionArray(value: unknown): QuestionArray | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const questions = value
        .map((entry) => sanitizeQuestion(entry))
        .filter((entry): entry is QuestionLike => entry !== null);

    return questions.length > 0 ? questions : undefined;
}

function sanitizeM5QuestionSolutions(value: unknown): M5QuestionSolution[] | undefined {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const items = value
        .map((entry) => {
            if (!isRecord(entry)) {
                return null;
            }

            const numero = readFiniteNumber(entry.numero);
            const solucionEsperada = readString(entry.solucion_esperada);
            if (numero === undefined || !solucionEsperada) {
                return null;
            }

            return {
                numero,
                solucion_esperada: solucionEsperada,
            } satisfies M5QuestionSolution;
        })
        .filter((entry): entry is M5QuestionSolution => entry !== null);

    return items.length > 0 ? items : undefined;
}

function buildFallbackQuestion(question: TeacherCaseSubmissionDetailQuestion): PreguntaMinimalista {
    return {
        numero: question.order,
        titulo: `Pregunta ${question.order}`,
        enunciado: question.context
            ? `${question.statement}\n\n${question.context}`
            : question.statement,
        solucion_esperada: question.expected_solution,
    };
}

function fallbackQuestionsFromModules(
    modules: TeacherCaseSubmissionDetailModule[],
    moduleId: TeacherCaseSubmissionDetailModule["id"],
): MinimalQuestionArray | undefined {
    const module = modules.find((entry) => entry.id === moduleId);
    if (!module || module.questions.length === 0) {
        return undefined;
    }

    return module.questions.map((question) => buildFallbackQuestion(question));
}

function fallbackM5SolutionsFromModules(
    modules: TeacherCaseSubmissionDetailModule[],
): M5QuestionSolution[] | undefined {
    const module = modules.find((entry) => entry.id === "M5");
    if (!module || module.questions.length === 0) {
        return undefined;
    }

    return module.questions
        .filter((question) => Boolean(question.expected_solution))
        .map((question) => ({
            numero: question.order,
            solucion_esperada: question.expected_solution,
        }));
}

function deriveCaseType(detail: TeacherCaseSubmissionDetailResponse): CaseType {
    return detail.modules.some((module) => module.id === "M2" || module.id === "M3")
        ? "harvard_with_eda"
        : "harvard_only";
}

function pickQuestionArray(
    primary: QuestionArray | undefined,
    fallback: QuestionArray | undefined,
): QuestionArray | undefined {
    return primary && primary.length > 0 ? primary : fallback;
}

function pickMinimalQuestionArray(
    primary: MinimalQuestionArray | undefined,
    fallback: MinimalQuestionArray | undefined,
): MinimalQuestionArray | undefined {
    return primary && primary.length > 0 ? primary : fallback;
}

function buildContent(detail: TeacherCaseSubmissionDetailResponse, source: Record<string, unknown>): CaseContent {
    const caseQuestions = pickMinimalQuestionArray(
        sanitizeMinimalQuestionArray(source.caseQuestions),
        fallbackQuestionsFromModules(detail.modules, "M1"),
    );
    const edaQuestions = pickQuestionArray(
        sanitizeQuestionArray(source.edaQuestions),
        fallbackQuestionsFromModules(detail.modules, "M2"),
    );
    const m3Questions = pickMinimalQuestionArray(
        sanitizeMinimalQuestionArray(source.m3Questions),
        fallbackQuestionsFromModules(detail.modules, "M3"),
    );
    const m4Questions = pickMinimalQuestionArray(
        sanitizeMinimalQuestionArray(source.m4Questions),
        fallbackQuestionsFromModules(detail.modules, "M4"),
    );
    const m5Questions = pickMinimalQuestionArray(
        sanitizeMinimalQuestionArray(source.m5Questions),
        fallbackQuestionsFromModules(detail.modules, "M5"),
    );

    return {
        instructions: readString(source.instructions),
        preguntaEje: readNonBlankString(source.preguntaEje),
        narrative: readString(source.narrative),
        financialExhibit: readString(source.financialExhibit),
        operatingExhibit: readString(source.operatingExhibit),
        stakeholdersExhibit: readString(source.stakeholdersExhibit),
        caseQuestions,
        edaReport: readString(source.edaReport),
        edaCharts: sanitizeChartArray(source.edaCharts),
        edaQuestions,
        teachingNote: readString(source.teachingNote) ?? detail.case.teaching_note ?? undefined,
        notebookCode: readString(source.notebookCode),
        datasetRows: sanitizeDatasetRows(source.datasetRows),
        doc7Dataset: sanitizeDatasetRows(source.doc7Dataset),
        m4Questions,
        m5Questions,
        m5QuestionsSolutions: sanitizeM5QuestionSolutions(source.m5QuestionsSolutions)
            ?? fallbackM5SolutionsFromModules(detail.modules),
        m3Content: readString(source.m3Content),
        m3Charts: sanitizeChartArray(source.m3Charts),
        m3Questions,
        m3NotebookCode: readString(source.m3NotebookCode),
        m4Content: readString(source.m4Content),
        m4Charts: sanitizeChartArray(source.m4Charts),
        m5Content: readString(source.m5Content),
    };
}

function buildModulesFallbackContent(detail: TeacherCaseSubmissionDetailResponse): CaseContent {
    const fallbackSource: Partial<Record<ContentQuestionKey, MinimalQuestionArray>> = {};

    for (const module of detail.modules) {
        const contentKey = MODULE_CONTENT_KEY_BY_ID[module.id];
        fallbackSource[contentKey] = module.questions.map((question) => buildFallbackQuestion(question));
    }

    return {
        caseQuestions: fallbackSource.caseQuestions,
        edaQuestions: fallbackSource.edaQuestions,
        m3Questions: fallbackSource.m3Questions,
        m4Questions: fallbackSource.m4Questions,
        m5Questions: fallbackSource.m5Questions,
        m5QuestionsSolutions: fallbackM5SolutionsFromModules(detail.modules),
        teachingNote: detail.case.teaching_note ?? undefined,
    };
}

export function toCanonicalCaseOutput(detail: TeacherCaseSubmissionDetailResponse): CanonicalCaseOutput {
    const source = sanitizeLooseRecord(detail.case_view) ?? {};
    const contentSource = sanitizeLooseRecord(source.content) ?? {};
    const caseType = isCaseType(source.caseType) ? source.caseType : deriveCaseType(detail);
    const content = buildContent(detail, contentSource);
    const hasAnyContent = Object.values(content).some((value) => {
        if (Array.isArray(value)) {
            return value.length > 0;
        }

        return value !== undefined && value !== null && value !== "";
    });

    return {
        caseId: readString(source.caseId) ?? detail.case.id,
        title: readString(source.title) ?? detail.case.title,
        subject: readString(source.subject) ?? "",
        syllabusModule: readString(source.syllabusModule) ?? "",
        guidingQuestion: readString(source.guidingQuestion) ?? "",
        industry: readString(source.industry) ?? "",
        academicLevel: readString(source.academicLevel) ?? "",
        caseType,
        edaDepth: isEdaDepth(source.edaDepth) ? source.edaDepth : undefined,
        studentProfile: isStudentProfile(source.studentProfile) ? source.studentProfile : "business",
        generatedAt: readString(source.generatedAt)
            ?? detail.response_state.submitted_at
            ?? detail.case.available_from
            ?? detail.case.deadline
            ?? EMPTY_GENERATED_AT,
        outputDepth: readString(source.outputDepth),
        content: hasAnyContent ? content : buildModulesFallbackContent(detail),
    };
}
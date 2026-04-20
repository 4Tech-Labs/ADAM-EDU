import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
    AlertCircle,
    BookOpen,
    ChevronRight,
    LoaderCircle,
    Plus,
    RefreshCcw,
    Save,
    Settings2,
    Trash2,
} from "lucide-react";

import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";
import type {
    TeacherCourseDraft,
    TeacherCourseTab,
} from "@/features/teacher-course/teacherCourseModel";
import {
    buildTeacherCourseDraft,
    buildTeacherSyllabusSaveRequest,
    createEmptyEvaluationStrategyItem,
    createEmptyTeacherSyllabusModule,
    createEmptyTeacherSyllabusPayload,
    createEmptyTeacherSyllabusUnit,
    formatAccessLinkStatus,
    formatTeacherCourseStatus,
    formatTeacherCourseTimestamp,
    getTeacherCoursePageErrorMessage,
    getTeacherCourseSaveErrorMessage,
    getTeacherCourseTab,
    isStaleSyllabusRevisionError,
    useSaveTeacherCourseSyllabus,
    useTeacherCourseDetail,
    validateTeacherCourseDraft,
} from "@/features/teacher-course/teacherCourseModel";
import type { ShowToast } from "@/shared/Toast";

const TEACHER_COURSE_PAGE_STYLES = `
.teacher-course-page .course-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1.5px solid transparent;
  color: #475569;
  font-size: 15px;
  font-weight: 600;
  transition: all 0.18s ease;
}
.teacher-course-page .course-nav-item:hover {
  background: #f8fafc;
  color: #1e293b;
}
.teacher-course-page .course-nav-item.active {
  background: #0144a0;
  border-color: #00337a;
  color: #fff;
  box-shadow: 0 8px 24px -16px rgba(1, 68, 160, 0.55);
}
.teacher-course-page .course-nav-item.active svg {
  color: #fff;
}
.teacher-course-page .course-nav-item svg {
  color: #94a3b8;
}
.teacher-course-page .section-divider {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
  padding-bottom: 14px;
}
.teacher-course-page .section-divider::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(to right, #0144a0 0%, #93c5fd 55%, transparent 100%);
}
.teacher-course-page .step-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  background: #0144a0;
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  box-shadow: 0 2px 8px rgba(1, 68, 160, 0.28);
}
.teacher-course-page .section-title {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0144a0;
}
.teacher-course-page .form-label {
  display: block;
  margin-bottom: 7px;
  color: #334155;
  font-size: 14px;
  font-weight: 700;
}
.teacher-course-page .form-hint {
  margin-top: 5px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}
.teacher-course-page .form-input {
  width: 100%;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fff;
  color: #0f172a;
  font-size: 15px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
  outline: none;
}
.teacher-course-page .form-input:hover:not(:focus):not(:disabled):not([readonly]) {
  border-color: #94a3b8;
}
.teacher-course-page .form-input:focus {
  border-color: #0144a0;
  box-shadow: 0 0 0 3px rgba(1, 68, 160, 0.12);
}
.teacher-course-page .form-input:disabled,
.teacher-course-page .form-input[readonly] {
  background: #f8fafc;
  color: #64748b;
}
.teacher-course-page .alert-strip {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  border-radius: 12px;
  padding: 14px 16px;
  font-size: 14px;
  line-height: 1.5;
}
.teacher-course-page .alert-info {
  background: #e8f0fe;
  color: #0144a0;
  border: 1px solid #bfdbfe;
}
.teacher-course-page .alert-warn {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}
.teacher-course-page .badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 800;
}
.teacher-course-page .badge-blue {
  color: #0144a0;
  background: #e8f0fe;
}
.teacher-course-page .footer-divider {
  border: none;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(to right, transparent 0%, #bfdbfe 25%, #0144a0 50%, #bfdbfe 75%, transparent 100%);
}
.teacher-course-page .module-shell[open] summary .module-chevron {
  transform: rotate(90deg);
}
.teacher-course-page .module-shell summary::-webkit-details-marker {
  display: none;
}
.teacher-course-page .module-chevron {
  transition: transform 0.18s ease;
}
`;

interface TeacherCoursePageProps {
    showToast: ShowToast;
}

interface SectionCardProps {
    step: number;
    title: string;
    highlightAdam?: boolean;
    subtitle?: string;
    children: React.ReactNode;
}

function SectionCard({
    step,
    title,
    highlightAdam = false,
    subtitle,
    children,
}: SectionCardProps) {
    return (
        <section className="rounded-[22px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
            <div className="section-divider">
                <span className="step-badge" aria-hidden="true">{step}</span>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="section-title">{title}</span>
                    {highlightAdam ? <span className="badge badge-blue">✦ ADAM</span> : null}
                    {subtitle ? (
                        <span className="text-sm font-normal normal-case tracking-normal text-slate-400">
                            {subtitle}
                        </span>
                    ) : null}
                </div>
            </div>
            {children}
        </section>
    );
}

function splitCommaSeparatedList(rawValue: string): string[] {
    return rawValue
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
}

function joinCommaSeparatedList(values: string[]): string {
    return values.join(", ");
}

function TeacherCourseLoadingState() {
    return (
        <TeacherLayout
            testId="teacher-course-loading"
            contentClassName="mx-auto max-w-[1440px] px-6 py-8"
        >
            <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
                <aside className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="animate-pulse space-y-4">
                        <div className="h-24 rounded-2xl bg-slate-200" />
                        <div className="h-12 rounded-xl bg-slate-100" />
                        <div className="h-12 rounded-xl bg-slate-100" />
                    </div>
                </aside>
                <div className="space-y-6">
                    <div className="animate-pulse rounded-[24px] border border-slate-200 bg-white p-8 shadow-sm">
                        <div className="h-8 w-80 rounded bg-slate-200" />
                        <div className="mt-4 h-4 w-[32rem] rounded bg-slate-100" />
                        <div className="mt-8 grid gap-4 md:grid-cols-2">
                            <div className="h-12 rounded-xl bg-slate-100" />
                            <div className="h-12 rounded-xl bg-slate-100" />
                            <div className="h-12 rounded-xl bg-slate-100" />
                            <div className="h-12 rounded-xl bg-slate-100" />
                        </div>
                    </div>
                </div>
            </div>
        </TeacherLayout>
    );
}

export function TeacherCoursePage({ showToast }: TeacherCoursePageProps) {
    const navigate = useNavigate();
    const { courseId = "" } = useParams<{ courseId: string }>();
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = getTeacherCourseTab(searchParams.get("tab"));
    const courseDetailQuery = useTeacherCourseDetail(courseId);
    const saveSyllabusMutation = useSaveTeacherCourseSyllabus(courseId);
    const [draft, setDraft] = useState<TeacherCourseDraft>(
        createEmptyTeacherSyllabusPayload(),
    );
    const [formError, setFormError] = useState<string | null>(null);

    useEffect(() => {
        if (courseDetailQuery.data) {
            setDraft(buildTeacherCourseDraft(courseDetailQuery.data));
            setFormError(null);
        }
    }, [courseDetailQuery.data]);

    const detail = courseDetailQuery.data;
    const pageErrorMessage = courseDetailQuery.error
        ? getTeacherCoursePageErrorMessage(
              courseDetailQuery.error,
              "No se pudo cargar el detalle del curso. Intenta refrescar la página.",
          )
        : null;

    const savedAtLabel = useMemo(
        () => formatTeacherCourseTimestamp(detail?.revision_metadata.saved_at ?? null),
        [detail?.revision_metadata.saved_at],
    );

    const revisionLabel = detail?.revision_metadata.current_revision ?? 0;

    function setTab(tab: TeacherCourseTab) {
        const nextParams = new URLSearchParams(searchParams);
        nextParams.set("tab", tab);
        setSearchParams(nextParams, { replace: true });
    }

    function updateDraft<K extends keyof TeacherCourseDraft>(
        field: K,
        value: TeacherCourseDraft[K],
    ) {
        setDraft((current) => ({ ...current, [field]: value }));
    }

    function updateSpecificObjective(index: number, value: string) {
        setDraft((current) => ({
            ...current,
            specific_objectives: current.specific_objectives.map((objective, currentIndex) =>
                currentIndex === index ? value : objective,
            ),
        }));
    }

    function addSpecificObjective() {
        setDraft((current) => ({
            ...current,
            specific_objectives: [...current.specific_objectives, ""],
        }));
    }

    function removeSpecificObjective(index: number) {
        setDraft((current) => ({
            ...current,
            specific_objectives: current.specific_objectives.filter(
                (_objective, currentIndex) => currentIndex !== index,
            ),
        }));
    }

    function updateBibliographyItem(index: number, value: string) {
        setDraft((current) => ({
            ...current,
            bibliography: current.bibliography.map((item, currentIndex) =>
                currentIndex === index ? value : item,
            ),
        }));
    }

    function addBibliographyItem() {
        setDraft((current) => ({
            ...current,
            bibliography: [...current.bibliography, ""],
        }));
    }

    function removeBibliographyItem(index: number) {
        setDraft((current) => ({
            ...current,
            bibliography: current.bibliography.filter(
                (_item, currentIndex) => currentIndex !== index,
            ),
        }));
    }

    function updateModuleField(
        moduleIndex: number,
        field: keyof TeacherCourseDraft["modules"][number],
        value: string | string[] | TeacherCourseDraft["modules"][number]["units"],
    ) {
        setDraft((current) => ({
            ...current,
            modules: current.modules.map((module, currentIndex) =>
                currentIndex === moduleIndex ? { ...module, [field]: value } : module,
            ),
        }));
    }

    function addModule() {
        setDraft((current) => ({
            ...current,
            modules: [...current.modules, createEmptyTeacherSyllabusModule()],
        }));
    }

    function removeModule(moduleIndex: number) {
        setDraft((current) => ({
            ...current,
            modules: current.modules.filter(
                (_module, currentIndex) => currentIndex !== moduleIndex,
            ),
        }));
    }

    function addModuleUnit(moduleIndex: number) {
        setDraft((current) => ({
            ...current,
            modules: current.modules.map((module, currentIndex) =>
                currentIndex === moduleIndex
                    ? {
                          ...module,
                          units: [...module.units, createEmptyTeacherSyllabusUnit()],
                      }
                    : module,
            ),
        }));
    }

    function updateModuleUnitField(
        moduleIndex: number,
        unitIndex: number,
        field: "title" | "topics",
        value: string,
    ) {
        setDraft((current) => ({
            ...current,
            modules: current.modules.map((module, currentIndex) =>
                currentIndex === moduleIndex
                    ? {
                          ...module,
                          units: module.units.map((unit, currentUnitIndex) =>
                              currentUnitIndex === unitIndex
                                  ? { ...unit, [field]: value }
                                  : unit,
                          ),
                      }
                    : module,
            ),
        }));
    }

    function removeModuleUnit(moduleIndex: number, unitIndex: number) {
        setDraft((current) => ({
            ...current,
            modules: current.modules.map((module, currentIndex) =>
                currentIndex === moduleIndex
                    ? {
                          ...module,
                          units: module.units.filter(
                              (_unit, currentUnitIndex) => currentUnitIndex !== unitIndex,
                          ),
                      }
                    : module,
            ),
        }));
    }

    function addEvaluationItem() {
        setDraft((current) => ({
            ...current,
            evaluation_strategy: [
                ...current.evaluation_strategy,
                createEmptyEvaluationStrategyItem(),
            ],
        }));
    }

    function updateEvaluationItemField(
        itemIndex: number,
        field: keyof TeacherCourseDraft["evaluation_strategy"][number],
        value: string | number | string[],
    ) {
        setDraft((current) => ({
            ...current,
            evaluation_strategy: current.evaluation_strategy.map((item, currentIndex) =>
                currentIndex === itemIndex ? { ...item, [field]: value } : item,
            ),
        }));
    }

    function removeEvaluationItem(itemIndex: number) {
        setDraft((current) => ({
            ...current,
            evaluation_strategy: current.evaluation_strategy.filter(
                (_item, currentIndex) => currentIndex !== itemIndex,
            ),
        }));
    }

    async function handleSave() {
        if (!detail) {
            return;
        }

        const validationMessage = validateTeacherCourseDraft(draft);
        if (validationMessage) {
            setFormError(validationMessage);
            showToast(validationMessage, "error");
            return;
        }

        setFormError(null);

        try {
            const response = await saveSyllabusMutation.mutateAsync(
                buildTeacherSyllabusSaveRequest(
                    detail.revision_metadata.current_revision,
                    draft,
                ),
            );
            setDraft(buildTeacherCourseDraft(response));
            showToast(
                "Syllabus guardado. ADAM usará la versión actualizada en próximas generaciones.",
                "success",
            );
        } catch (error) {
            const message = getTeacherCourseSaveErrorMessage(
                error,
                "No se pudo guardar el syllabus. Intenta nuevamente.",
            );
            setFormError(message);

            if (isStaleSyllabusRevisionError(error)) {
                await courseDetailQuery.refetch();
            }

            showToast(message, "error");
        }
    }

    if (courseDetailQuery.isLoading) {
        return <TeacherCourseLoadingState />;
    }

    if (!courseId || !detail) {
        return (
            <TeacherLayout
                testId="teacher-course-page"
                contentClassName="mx-auto max-w-[1440px] px-6 py-8"
            >
                <style>{TEACHER_COURSE_PAGE_STYLES}</style>
                <section
                    className="rounded-[24px] border border-red-200 bg-white p-8 shadow-sm"
                    data-testid="global-page-error"
                >
                    <div className="flex items-start gap-3 text-red-700">
                        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                        <div>
                            <h1 className="text-lg font-bold text-slate-900">
                                No se pudo abrir este curso
                            </h1>
                            <p className="mt-2 max-w-2xl text-sm text-slate-600">
                                {pageErrorMessage ||
                                    "La ruta no contiene un identificador de curso válido o el recurso ya no está disponible."}
                            </p>
                            <div className="mt-5 flex flex-wrap gap-3">
                                <button
                                    type="button"
                                    onClick={() => void courseDetailQuery.refetch()}
                                    className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
                                >
                                    <RefreshCcw className="h-4 w-4" />
                                    Reintentar
                                </button>
                                <button
                                    type="button"
                                    onClick={() => navigate("/teacher/dashboard")}
                                    className="inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#00337a]"
                                >
                                    Volver al dashboard
                                </button>
                            </div>
                        </div>
                    </div>
                </section>
            </TeacherLayout>
        );
    }

    const isSaving = saveSyllabusMutation.isPending;

    return (
        <TeacherLayout
            testId="teacher-course-page"
            contentClassName="mx-auto max-w-[1440px] px-6 py-8"
        >
            <style>{TEACHER_COURSE_PAGE_STYLES}</style>
            <div className="teacher-course-page grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
                <aside className="h-fit rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm lg:sticky lg:top-[104px]">
                    <div className="rounded-[18px] border border-[#00337a] bg-[#0144a0] p-4 shadow-md">
                        <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="rounded-full border border-blue-100 bg-white px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[#0144a0]">
                                {formatTeacherCourseStatus(detail.course.status)}
                            </span>
                            <span className="text-xs font-bold text-blue-100">
                                {detail.course.semester}
                            </span>
                        </div>
                        <p className="text-[15px] font-bold leading-snug text-white">
                            {detail.course.title}
                        </p>
                        <p className="mt-1 text-[13px] font-semibold text-blue-200">
                            {detail.course.academic_level}
                        </p>
                        <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-blue-100">
                            <div className="rounded-xl bg-white/10 px-3 py-2">
                                <span className="block text-[11px] uppercase tracking-wide text-blue-200">
                                    Código
                                </span>
                                <span className="mt-1 block font-semibold text-white">
                                    {detail.course.code}
                                </span>
                            </div>
                            <div className="rounded-xl bg-white/10 px-3 py-2">
                                <span className="block text-[11px] uppercase tracking-wide text-blue-200">
                                    Revisión
                                </span>
                                <span className="mt-1 block font-semibold text-white">
                                    R{revisionLabel}
                                </span>
                            </div>
                        </div>
                    </div>

                    <nav className="mt-4 flex flex-col gap-2" aria-label="Secciones del curso">
                        <button
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "syllabus"}
                            aria-controls="teacher-course-syllabus-panel"
                            className={`course-nav-item ${activeTab === "syllabus" ? "active" : ""}`}
                            onClick={() => setTab("syllabus")}
                        >
                            <BookOpen className="h-5 w-5" />
                            <span>Syllabus</span>
                            <span className="ml-auto rounded-full bg-amber-400/90 px-2 py-0.5 text-[11px] font-bold text-slate-900">
                                R{revisionLabel}
                            </span>
                        </button>
                        <button
                            type="button"
                            role="tab"
                            aria-selected={activeTab === "configuracion"}
                            aria-controls="teacher-course-config-panel"
                            className={`course-nav-item ${activeTab === "configuracion" ? "active" : ""}`}
                            onClick={() => setTab("configuracion")}
                        >
                            <Settings2 className="h-5 w-5" />
                            <span>Configuración</span>
                        </button>
                    </nav>
                </aside>

                <div className="min-w-0 space-y-6">
                    {activeTab === "syllabus" ? (
                        <div
                            id="teacher-course-syllabus-panel"
                            role="tabpanel"
                            aria-labelledby="syllabus"
                            className="space-y-6"
                        >
                            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                                    <div>
                                        <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                                            Syllabus de la asignatura
                                        </h1>
                                        <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                                            Este documento es utilizado por ADAM para generar casos y actividades alineadas al curso.
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-3">
                                        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
                                            <span className="font-semibold text-slate-900">Último guardado:</span>{" "}
                                            <span>{savedAtLabel}</span>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => void handleSave()}
                                            disabled={isSaving}
                                            className="inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-5 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#00337a] disabled:cursor-wait disabled:opacity-70"
                                        >
                                            {isSaving ? (
                                                <LoaderCircle className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Save className="h-4 w-4" />
                                            )}
                                            {isSaving ? "Guardando..." : "Guardar cambios"}
                                        </button>
                                    </div>
                                </div>
                            </section>

                            <div className="alert-strip alert-info">
                                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                                <span>
                                    Los campos marcados con <strong>✦ ADAM</strong> son leídos automáticamente por el sistema para generar casos adaptados al syllabus.
                                </span>
                            </div>

                            {formError ? (
                                <div className="alert-strip alert-warn" role="alert">
                                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                                    <span>{formError}</span>
                                </div>
                            ) : null}

                            <SectionCard step={1} title="Identificación de la Asignatura" highlightAdam>
                                <div className="grid gap-5 md:grid-cols-2">
                                    <div>
                                        <label className="form-label" htmlFor="course-title">
                                            Nombre de la asignatura
                                        </label>
                                        <input
                                            id="course-title"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.title}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="course-code">
                                            Código
                                        </label>
                                        <input
                                            id="course-code"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.code}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="syllabus-department">
                                            Departamento que la ofrece
                                        </label>
                                        <input
                                            id="syllabus-department"
                                            className="form-input"
                                            value={draft.department}
                                            onChange={(event) => updateDraft("department", event.target.value)}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="syllabus-knowledge-area">
                                            Área de conocimiento
                                        </label>
                                        <input
                                            id="syllabus-knowledge-area"
                                            className="form-input"
                                            value={draft.knowledge_area}
                                            onChange={(event) =>
                                                updateDraft("knowledge_area", event.target.value)
                                            }
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="syllabus-nbc">
                                            Núcleo Básico del Conocimiento (NBC)
                                        </label>
                                        <input
                                            id="syllabus-nbc"
                                            className="form-input"
                                            value={draft.nbc}
                                            onChange={(event) => updateDraft("nbc", event.target.value)}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="syllabus-version-label">
                                            Versión del syllabus
                                        </label>
                                        <input
                                            id="syllabus-version-label"
                                            className="form-input"
                                            value={draft.version_label}
                                            onChange={(event) =>
                                                updateDraft("version_label", event.target.value)
                                            }
                                        />
                                        <p className="form-hint">
                                            Revisión actual: R{revisionLabel}. Última actualización registrada: {savedAtLabel}.
                                        </p>
                                    </div>
                                </div>
                            </SectionCard>

                            <SectionCard step={2} title="Carga Académica y Contexto Institucional">
                                <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
                                    <div>
                                        <label className="form-label" htmlFor="course-semester">
                                            Semestre
                                        </label>
                                        <input
                                            id="course-semester"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.semester}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="course-academic-level">
                                            Nivel académico
                                        </label>
                                        <input
                                            id="course-academic-level"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.academic_level}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="course-max-students">
                                            Cupo máximo
                                        </label>
                                        <input
                                            id="course-max-students"
                                            className="form-input"
                                            readOnly
                                            value={String(detail.course.max_students)}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="course-students-count">
                                            Estudiantes activos
                                        </label>
                                        <input
                                            id="course-students-count"
                                            className="form-input"
                                            readOnly
                                            value={String(detail.course.students_count)}
                                        />
                                    </div>
                                </div>
                                <div className="mt-5">
                                    <label className="form-label" htmlFor="syllabus-academic-load">
                                        Carga académica y logística del curso
                                    </label>
                                    <textarea
                                        id="syllabus-academic-load"
                                        className="form-input min-h-[140px]"
                                        value={draft.academic_load}
                                        onChange={(event) => updateDraft("academic_load", event.target.value)}
                                    />
                                    <p className="form-hint">
                                        Resume aquí créditos, distribución de horas, modalidad, idioma, prerrequisitos u otras condiciones operativas del curso.
                                    </p>
                                </div>
                            </SectionCard>

                            <SectionCard step={3} title="Descripción de la Asignatura" highlightAdam>
                                <div>
                                    <label className="form-label" htmlFor="syllabus-course-description">
                                        Descripción
                                    </label>
                                    <textarea
                                        id="syllabus-course-description"
                                        className="form-input min-h-[220px]"
                                        value={draft.course_description}
                                        onChange={(event) =>
                                            updateDraft("course_description", event.target.value)
                                        }
                                    />
                                </div>
                            </SectionCard>

                            <SectionCard step={4} title="Objetivos de Aprendizaje" highlightAdam>
                                <div className="space-y-5">
                                    <div>
                                        <label className="form-label" htmlFor="syllabus-general-objective">
                                            Objetivo general
                                        </label>
                                        <textarea
                                            id="syllabus-general-objective"
                                            className="form-input min-h-[140px]"
                                            value={draft.general_objective}
                                            onChange={(event) =>
                                                updateDraft("general_objective", event.target.value)
                                            }
                                        />
                                    </div>
                                    <div>
                                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                            <div>
                                                <label className="form-label mb-0">
                                                    Objetivos específicos
                                                </label>
                                                <p className="form-hint">
                                                    Un objetivo por fila. Inicia cada uno con un verbo en infinitivo.
                                                </p>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={addSpecificObjective}
                                                className="inline-flex items-center gap-2 self-start rounded-xl border border-[#bfdbfe] bg-[#e8f0fe] px-4 py-2 text-sm font-bold text-[#0144a0] transition hover:bg-blue-100"
                                            >
                                                <Plus className="h-4 w-4" />
                                                Agregar objetivo
                                            </button>
                                        </div>
                                        <div className="mt-4 space-y-3">
                                            {draft.specific_objectives.length === 0 ? (
                                                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-500">
                                                    Aún no hay objetivos específicos cargados.
                                                </div>
                                            ) : null}
                                            {draft.specific_objectives.map((objective, index) => (
                                                <div
                                                    key={`objective-${index}`}
                                                    className="flex gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4"
                                                >
                                                    <span className="mt-3 w-8 shrink-0 text-sm font-bold text-[#0144a0]">
                                                        O{index + 1}
                                                    </span>
                                                    <input
                                                        aria-label={`Objetivo específico ${index + 1}`}
                                                        className="form-input"
                                                        value={objective}
                                                        onChange={(event) =>
                                                            updateSpecificObjective(index, event.target.value)
                                                        }
                                                    />
                                                    <button
                                                        type="button"
                                                        aria-label={`Eliminar objetivo específico ${index + 1}`}
                                                        className="mt-2 self-start rounded-lg p-2 text-slate-400 transition hover:bg-white hover:text-red-500"
                                                        onClick={() => removeSpecificObjective(index)}
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </SectionCard>

                            <SectionCard step={5} title="Contenidos por Módulo" highlightAdam>
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                                    <p className="max-w-3xl text-sm text-slate-400">
                                        Cada módulo es usado por ADAM para determinar el tema y nivel de profundidad de los casos a generar.
                                    </p>
                                    <button
                                        type="button"
                                        onClick={addModule}
                                        className="inline-flex items-center gap-2 self-start rounded-xl border border-[#bfdbfe] bg-[#e8f0fe] px-4 py-2 text-sm font-bold text-[#0144a0] transition hover:bg-blue-100"
                                    >
                                        <Plus className="h-4 w-4" />
                                        Agregar módulo
                                    </button>
                                </div>

                                <div className="mt-5 space-y-4">
                                    {draft.modules.length === 0 ? (
                                        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                                            Aún no hay módulos cargados. Agrega el primero para estructurar el syllabus.
                                        </div>
                                    ) : null}

                                    {draft.modules.map((module, moduleIndex) => (
                                        <details
                                            key={module.module_id}
                                            className="module-shell overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
                                            open
                                        >
                                            <summary className="flex cursor-pointer list-none items-center gap-4 bg-slate-50 px-5 py-4 transition hover:bg-slate-100">
                                                <ChevronRight className="module-chevron h-5 w-5 shrink-0 text-slate-400" />
                                                <span className="text-sm font-bold uppercase tracking-wide text-[#0144a0]">
                                                    Módulo {moduleIndex + 1}
                                                </span>
                                                <span className="min-w-0 truncate text-base font-bold text-slate-700">
                                                    {module.module_title.trim() || "Sin título"}
                                                </span>
                                                <button
                                                    type="button"
                                                    aria-label={`Eliminar módulo ${moduleIndex + 1}`}
                                                    className="ml-auto rounded-lg p-2 text-slate-400 transition hover:bg-white hover:text-red-500"
                                                    onClick={(event) => {
                                                        event.preventDefault();
                                                        event.stopPropagation();
                                                        removeModule(moduleIndex);
                                                    }}
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </summary>
                                            <div className="space-y-6 px-6 py-6">
                                                <div className="grid gap-5 md:grid-cols-2">
                                                    <div>
                                                        <label className="form-label" htmlFor={`module-title-${moduleIndex}`}>
                                                            Título del módulo
                                                        </label>
                                                        <input
                                                            id={`module-title-${moduleIndex}`}
                                                            className="form-input"
                                                            value={module.module_title}
                                                            onChange={(event) =>
                                                                updateModuleField(
                                                                    moduleIndex,
                                                                    "module_title",
                                                                    event.target.value,
                                                                )
                                                            }
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="form-label" htmlFor={`module-weeks-${moduleIndex}`}>
                                                            Semanas
                                                        </label>
                                                        <input
                                                            id={`module-weeks-${moduleIndex}`}
                                                            className="form-input"
                                                            value={module.weeks}
                                                            onChange={(event) =>
                                                                updateModuleField(
                                                                    moduleIndex,
                                                                    "weeks",
                                                                    event.target.value,
                                                                )
                                                            }
                                                        />
                                                    </div>
                                                </div>

                                                <div>
                                                    <label className="form-label" htmlFor={`module-summary-${moduleIndex}`}>
                                                        Resumen del módulo
                                                    </label>
                                                    <textarea
                                                        id={`module-summary-${moduleIndex}`}
                                                        className="form-input min-h-[120px]"
                                                        value={module.module_summary}
                                                        onChange={(event) =>
                                                            updateModuleField(
                                                                moduleIndex,
                                                                "module_summary",
                                                                event.target.value,
                                                            )
                                                        }
                                                    />
                                                </div>

                                                <div className="grid gap-5 md:grid-cols-2">
                                                    <div>
                                                        <label className="form-label" htmlFor={`module-outcomes-${moduleIndex}`}>
                                                            Resultados de aprendizaje
                                                        </label>
                                                        <input
                                                            id={`module-outcomes-${moduleIndex}`}
                                                            className="form-input"
                                                            value={joinCommaSeparatedList(module.learning_outcomes)}
                                                            onChange={(event) =>
                                                                updateModuleField(
                                                                    moduleIndex,
                                                                    "learning_outcomes",
                                                                    splitCommaSeparatedList(event.target.value),
                                                                )
                                                            }
                                                        />
                                                        <p className="form-hint">
                                                            Usa comas para separar varios resultados.
                                                        </p>
                                                    </div>
                                                    <div>
                                                        <label className="form-label" htmlFor={`module-connections-${moduleIndex}`}>
                                                            Conexión con otras asignaturas
                                                        </label>
                                                        <input
                                                            id={`module-connections-${moduleIndex}`}
                                                            className="form-input"
                                                            value={module.cross_course_connections}
                                                            onChange={(event) =>
                                                                updateModuleField(
                                                                    moduleIndex,
                                                                    "cross_course_connections",
                                                                    event.target.value,
                                                                )
                                                            }
                                                        />
                                                    </div>
                                                </div>

                                                <div>
                                                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                                        <div>
                                                            <label className="form-label mb-0">
                                                                Unidades temáticas
                                                            </label>
                                                            <p className="form-hint">
                                                                Cada unidad mantiene el shape canónico modules -&gt; units esperado por el backend.
                                                            </p>
                                                        </div>
                                                        <button
                                                            type="button"
                                                            onClick={() => addModuleUnit(moduleIndex)}
                                                            className="inline-flex items-center gap-2 self-start rounded-xl border border-[#bfdbfe] bg-[#e8f0fe] px-4 py-2 text-sm font-bold text-[#0144a0] transition hover:bg-blue-100"
                                                        >
                                                            <Plus className="h-4 w-4" />
                                                            Agregar unidad
                                                        </button>
                                                    </div>

                                                    <div className="mt-4 space-y-4">
                                                        {module.units.map((unit, unitIndex) => (
                                                            <div
                                                                key={unit.unit_id}
                                                                className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4"
                                                            >
                                                                <div className="mb-4 flex items-center justify-between gap-3">
                                                                    <span className="inline-flex rounded-lg bg-blue-100 px-3 py-1 text-xs font-bold text-[#0144a0]">
                                                                        {moduleIndex + 1}.{unitIndex + 1}
                                                                    </span>
                                                                    <button
                                                                        type="button"
                                                                        aria-label={`Eliminar unidad ${moduleIndex + 1}.${unitIndex + 1}`}
                                                                        className="rounded-lg p-2 text-slate-400 transition hover:bg-white hover:text-red-500"
                                                                        onClick={() =>
                                                                            removeModuleUnit(moduleIndex, unitIndex)
                                                                        }
                                                                    >
                                                                        <Trash2 className="h-4 w-4" />
                                                                    </button>
                                                                </div>
                                                                <div className="grid gap-4">
                                                                    <div>
                                                                        <label className="form-label" htmlFor={`module-${moduleIndex}-unit-${unitIndex}-title`}>
                                                                            Título de la unidad
                                                                        </label>
                                                                        <input
                                                                            id={`module-${moduleIndex}-unit-${unitIndex}-title`}
                                                                            className="form-input"
                                                                            value={unit.title}
                                                                            onChange={(event) =>
                                                                                updateModuleUnitField(
                                                                                    moduleIndex,
                                                                                    unitIndex,
                                                                                    "title",
                                                                                    event.target.value,
                                                                                )
                                                                            }
                                                                        />
                                                                    </div>
                                                                    <div>
                                                                        <label className="form-label" htmlFor={`module-${moduleIndex}-unit-${unitIndex}-topics`}>
                                                                            Contenidos
                                                                        </label>
                                                                        <textarea
                                                                            id={`module-${moduleIndex}-unit-${unitIndex}-topics`}
                                                                            className="form-input min-h-[100px]"
                                                                            value={unit.topics}
                                                                            onChange={(event) =>
                                                                                updateModuleUnitField(
                                                                                    moduleIndex,
                                                                                    unitIndex,
                                                                                    "topics",
                                                                                    event.target.value,
                                                                                )
                                                                            }
                                                                        />
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            </div>
                                        </details>
                                    ))}
                                </div>
                            </SectionCard>

                            <SectionCard step={6} title="Estrategia de Evaluación">
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                                    <p className="max-w-3xl text-sm text-slate-400">
                                        Define las actividades evaluativas y el resultado de aprendizaje esperado para cada una.
                                    </p>
                                    <button
                                        type="button"
                                        onClick={addEvaluationItem}
                                        className="inline-flex items-center gap-2 self-start rounded-xl border border-[#bfdbfe] bg-[#e8f0fe] px-4 py-2 text-sm font-bold text-[#0144a0] transition hover:bg-blue-100"
                                    >
                                        <Plus className="h-4 w-4" />
                                        Agregar actividad
                                    </button>
                                </div>
                                <div className="mt-5 space-y-3">
                                    {draft.evaluation_strategy.length === 0 ? (
                                        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                                            Aún no hay actividades evaluativas configuradas.
                                        </div>
                                    ) : null}
                                    {draft.evaluation_strategy.map((item, itemIndex) => (
                                        <div
                                            key={`evaluation-${itemIndex}`}
                                            className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 xl:grid-cols-[minmax(0,2fr)_110px_minmax(0,1fr)_minmax(0,2fr)_auto]"
                                        >
                                            <div>
                                                <label className="form-label" htmlFor={`evaluation-activity-${itemIndex}`}>
                                                    Actividad evaluativa
                                                </label>
                                                <input
                                                    id={`evaluation-activity-${itemIndex}`}
                                                    className="form-input"
                                                    value={item.activity}
                                                    onChange={(event) =>
                                                        updateEvaluationItemField(
                                                            itemIndex,
                                                            "activity",
                                                            event.target.value,
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <label className="form-label" htmlFor={`evaluation-weight-${itemIndex}`}>
                                                    Peso %
                                                </label>
                                                <input
                                                    id={`evaluation-weight-${itemIndex}`}
                                                    className="form-input"
                                                    type="number"
                                                    min="0"
                                                    step="0.1"
                                                    value={item.weight}
                                                    onChange={(event) =>
                                                        updateEvaluationItemField(
                                                            itemIndex,
                                                            "weight",
                                                            Number(event.target.value),
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <label className="form-label" htmlFor={`evaluation-objectives-${itemIndex}`}>
                                                    Objetivos vinculados
                                                </label>
                                                <input
                                                    id={`evaluation-objectives-${itemIndex}`}
                                                    className="form-input"
                                                    value={joinCommaSeparatedList(item.linked_objectives)}
                                                    onChange={(event) =>
                                                        updateEvaluationItemField(
                                                            itemIndex,
                                                            "linked_objectives",
                                                            splitCommaSeparatedList(event.target.value),
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div>
                                                <label className="form-label" htmlFor={`evaluation-outcome-${itemIndex}`}>
                                                    Resultado esperado
                                                </label>
                                                <input
                                                    id={`evaluation-outcome-${itemIndex}`}
                                                    className="form-input"
                                                    value={item.expected_outcome}
                                                    onChange={(event) =>
                                                        updateEvaluationItemField(
                                                            itemIndex,
                                                            "expected_outcome",
                                                            event.target.value,
                                                        )
                                                    }
                                                />
                                            </div>
                                            <div className="flex items-end">
                                                <button
                                                    type="button"
                                                    aria-label={`Eliminar actividad evaluativa ${itemIndex + 1}`}
                                                    className="rounded-lg p-3 text-slate-400 transition hover:bg-white hover:text-red-500"
                                                    onClick={() => removeEvaluationItem(itemIndex)}
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </SectionCard>

                            <SectionCard step={7} title="Estrategias Didácticas">
                                <div className="space-y-5">
                                    <div>
                                        <label className="form-label" htmlFor="didactic-methodological-perspective">
                                            Perspectiva metodológica
                                        </label>
                                        <textarea
                                            id="didactic-methodological-perspective"
                                            className="form-input min-h-[180px]"
                                            value={draft.didactic_strategy.methodological_perspective}
                                            onChange={(event) =>
                                                updateDraft("didactic_strategy", {
                                                    ...draft.didactic_strategy,
                                                    methodological_perspective: event.target.value,
                                                })
                                            }
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="didactic-pedagogical-modality">
                                            Modalidad pedagógica
                                        </label>
                                        <textarea
                                            id="didactic-pedagogical-modality"
                                            className="form-input min-h-[180px]"
                                            value={draft.didactic_strategy.pedagogical_modality}
                                            onChange={(event) =>
                                                updateDraft("didactic_strategy", {
                                                    ...draft.didactic_strategy,
                                                    pedagogical_modality: event.target.value,
                                                })
                                            }
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="integrative-project">
                                            Proyecto integrador
                                        </label>
                                        <textarea
                                            id="integrative-project"
                                            className="form-input min-h-[220px]"
                                            value={draft.integrative_project}
                                            onChange={(event) =>
                                                updateDraft("integrative_project", event.target.value)
                                            }
                                        />
                                    </div>
                                </div>
                            </SectionCard>

                            <SectionCard step={8} title="Bibliografía">
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                                    <p className="max-w-3xl text-sm text-slate-400">
                                        Registra las referencias clave del curso. Cada fila se guardará como un elemento independiente del arreglo `bibliography`.
                                    </p>
                                    <button
                                        type="button"
                                        onClick={addBibliographyItem}
                                        className="inline-flex items-center gap-2 self-start rounded-xl border border-[#bfdbfe] bg-[#e8f0fe] px-4 py-2 text-sm font-bold text-[#0144a0] transition hover:bg-blue-100"
                                    >
                                        <Plus className="h-4 w-4" />
                                        Agregar referencia
                                    </button>
                                </div>

                                <div className="mt-5 space-y-3">
                                    {draft.bibliography.length === 0 ? (
                                        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                                            Aún no hay referencias bibliográficas cargadas.
                                        </div>
                                    ) : null}
                                    {draft.bibliography.map((item, index) => (
                                        <div
                                            key={`bibliography-${index}`}
                                            className="flex gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4"
                                        >
                                            <textarea
                                                aria-label={`Referencia bibliográfica ${index + 1}`}
                                                className="form-input min-h-[96px]"
                                                value={item}
                                                onChange={(event) =>
                                                    updateBibliographyItem(index, event.target.value)
                                                }
                                            />
                                            <button
                                                type="button"
                                                aria-label={`Eliminar referencia bibliográfica ${index + 1}`}
                                                className="mt-2 self-start rounded-lg p-2 text-slate-400 transition hover:bg-white hover:text-red-500"
                                                onClick={() => removeBibliographyItem(index)}
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </SectionCard>

                            <SectionCard
                                step={9}
                                title="Observaciones del Docente"
                                subtitle="(no visible para estudiantes)"
                            >
                                <div>
                                    <label className="form-label" htmlFor="teacher-notes">
                                        Notas internas del curso
                                    </label>
                                    <textarea
                                        id="teacher-notes"
                                        className="form-input min-h-[140px]"
                                        value={draft.teacher_notes}
                                        onChange={(event) => updateDraft("teacher_notes", event.target.value)}
                                    />
                                </div>
                            </SectionCard>

                            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                                <hr className="footer-divider mb-6" />
                                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                                    <div className="space-y-1 text-sm text-slate-500">
                                        <p>
                                            Último guardado: <span className="font-semibold text-slate-900">{savedAtLabel}</span>
                                        </p>
                                        <p>
                                            Revisión vigente: <span className="font-semibold text-slate-900">R{revisionLabel}</span>
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => void handleSave()}
                                        disabled={isSaving}
                                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#0144a0] px-8 py-3 text-base font-bold text-white shadow-md transition hover:bg-[#00337a] disabled:cursor-wait disabled:opacity-70"
                                    >
                                        {isSaving ? (
                                            <LoaderCircle className="h-5 w-5 animate-spin" />
                                        ) : (
                                            <Save className="h-5 w-5" />
                                        )}
                                        {isSaving ? "Guardando..." : "Guardar y publicar"}
                                    </button>
                                </div>
                            </section>
                        </div>
                    ) : (
                        <div
                            id="teacher-course-config-panel"
                            role="tabpanel"
                            aria-labelledby="configuracion"
                            className="space-y-6"
                        >
                            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                                <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                                    Configuración del Curso
                                </h1>
                                <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                                    Información institucional del curso y metadata real del enlace de acceso para estudiantes.
                                </p>
                            </section>

                            <SectionCard step={1} title="Información Institucional">
                                <p className="mb-5 text-sm text-slate-400">
                                    Estos datos son gestionados por la administración institucional y no pueden ser modificados por el docente.
                                </p>
                                <div className="grid gap-5 md:grid-cols-2">
                                    <div>
                                        <label className="form-label" htmlFor="configuration-title">
                                            Nombre de la asignatura
                                        </label>
                                        <input
                                            id="configuration-title"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.title}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-code">
                                            Código del curso
                                        </label>
                                        <input
                                            id="configuration-code"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.code}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-semester">
                                            Semestre
                                        </label>
                                        <input
                                            id="configuration-semester"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.semester}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-level">
                                            Nivel de formación
                                        </label>
                                        <input
                                            id="configuration-level"
                                            className="form-input"
                                            readOnly
                                            value={detail.course.academic_level}
                                        />
                                    </div>
                                </div>
                            </SectionCard>

                            <SectionCard step={2} title="Acceso de Estudiantes">
                                <div className="alert-strip alert-info mb-6">
                                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                                    <span>
                                        Esta vista solo muestra la metadata entregada por el backend. El contrato actual no expone un raw invite link reutilizable, por eso aquí no aparecen acciones de copiar o regenerar tokens.
                                    </span>
                                </div>

                                <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
                                    <div>
                                        <label className="form-label" htmlFor="configuration-access-status">
                                            Estado del enlace
                                        </label>
                                        <input
                                            id="configuration-access-status"
                                            className="form-input"
                                            readOnly
                                            value={formatAccessLinkStatus(
                                                detail.configuration.access_link_status,
                                            )}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-access-id">
                                            Access link ID
                                        </label>
                                        <input
                                            id="configuration-access-id"
                                            className="form-input font-mono text-sm"
                                            readOnly
                                            value={detail.configuration.access_link_id ?? "No disponible"}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-created-at">
                                            Creado en
                                        </label>
                                        <input
                                            id="configuration-created-at"
                                            className="form-input"
                                            readOnly
                                            value={formatTeacherCourseTimestamp(
                                                detail.configuration.access_link_created_at,
                                            )}
                                        />
                                    </div>
                                    <div>
                                        <label className="form-label" htmlFor="configuration-join-path">
                                            Join path
                                        </label>
                                        <input
                                            id="configuration-join-path"
                                            className="form-input font-mono text-sm"
                                            readOnly
                                            value={detail.configuration.join_path}
                                        />
                                    </div>
                                </div>
                            </SectionCard>
                        </div>
                    )}
                </div>
            </div>
        </TeacherLayout>
    );
}

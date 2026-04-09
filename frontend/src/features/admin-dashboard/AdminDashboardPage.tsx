import {
    Archive,
    BarChart3,
    BookOpen,
    Copy,
    ExternalLink,
    LogOut,
    MailPlus,
    Pencil,
    Plus,
    Search,
    TriangleAlert,
    Users,
    X,
} from "lucide-react";
import {
    useCallback,
    useDeferredValue,
    useEffect,
    useId,
    useMemo,
    useRef,
    useState,
    type Dispatch,
    type FormEvent,
    type HTMLInputTypeAttribute,
    type ReactNode,
    type SetStateAction,
} from "react";

import { useAuth } from "@/app/auth/useAuth";
import type {
    AdminCourseListItem,
    AdminCourseListResponse,
    AdminCourseStatus,
    AdminDashboardSummaryResponse,
    AdminTeacherOptionsResponse,
} from "@/shared/adam-types";
import { ApiError, api } from "@/shared/api";
import type { ShowToast } from "@/shared/Toast";
import {
    ADMIN_PAGE_SIZE,
    ACADEMIC_LEVEL_OPTIONS,
    COURSE_STATUS_OPTIONS,
    EMPTY_COURSES,
    buildCourseFormFromItem,
    buildCoursePayload,
    buildLinkPresentation,
    copyToClipboard,
    createEmptyCourseForm,
    encodeTeacherOptionValue,
    getAdminErrorMessage,
    getCapacityColor,
    getCourseStatusMeta,
    getInitials,
    getTeacherStateMeta,
    sortPendingInvites,
    summarizePageRange,
    teacherInviteToPendingOption,
    type CourseFormState,
    type LinkPresentation,
    type TeacherOptionsState,
} from "./adminDashboardModel";

type ModalInviteTarget = "create" | "edit";

interface InviteSuccessState {
    email: string;
    activationLink: string;
}

interface Props {
    showToast: ShowToast;
}

export function AdminDashboardPage({ showToast }: Props) {
    const { actor, signOut } = useAuth();
    const semesterFilterListId = useId();

    const [summary, setSummary] = useState<AdminDashboardSummaryResponse | null>(null);
    const [coursesResponse, setCoursesResponse] = useState<AdminCourseListResponse | null>(null);
    const [pageLoading, setPageLoading] = useState(true);
    const [pageError, setPageError] = useState<string | null>(null);
    const [teacherOptionsState, setTeacherOptionsState] = useState<TeacherOptionsState>({
        data: null,
        loading: false,
        error: null,
    });
    const [transientAccessLinks, setTransientAccessLinks] = useState<Record<string, string>>({});
    const [search, setSearch] = useState("");
    const deferredSearch = useDeferredValue(search);
    const [semesterFilter, setSemesterFilter] = useState("");
    const [statusFilter, setStatusFilter] = useState("all");
    const [academicLevelFilter, setAcademicLevelFilter] = useState("all");
    const [page, setPage] = useState(1);
    const [reloadTick, setReloadTick] = useState(0);
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const [isEditOpen, setIsEditOpen] = useState(false);
    const [isArchiveOpen, setIsArchiveOpen] = useState(false);
    const [isInviteOpen, setIsInviteOpen] = useState(false);
    const [createForm, setCreateForm] = useState<CourseFormState>(createEmptyCourseForm());
    const [editForm, setEditForm] = useState<CourseFormState>(createEmptyCourseForm());
    const [inviteTarget, setInviteTarget] = useState<ModalInviteTarget>("create");
    const [editingCourseId, setEditingCourseId] = useState<string | null>(null);
    const [archivingCourseId, setArchivingCourseId] = useState<string | null>(null);
    const [inviteName, setInviteName] = useState("");
    const [inviteEmail, setInviteEmail] = useState("");
    const [inviteSuccess, setInviteSuccess] = useState<InviteSuccessState | null>(null);
    const [submittingCreate, setSubmittingCreate] = useState(false);
    const [submittingEdit, setSubmittingEdit] = useState(false);
    const [submittingArchive, setSubmittingArchive] = useState(false);
    const [submittingInvite, setSubmittingInvite] = useState(false);
    const [regeneratingCourseId, setRegeneratingCourseId] = useState<string | null>(null);
    const [courseFormError, setCourseFormError] = useState<string | null>(null);
    const [inviteFormError, setInviteFormError] = useState<string | null>(null);
    const lastExternalRefreshAtRef = useRef(0);

    const currentItems = useMemo(() => coursesResponse?.items ?? EMPTY_COURSES, [coursesResponse]);
    const editingCourse = editingCourseId
        ? currentItems.find((item) => item.id === editingCourseId) ?? null
        : null;
    const archivingCourse = archivingCourseId
        ? currentItems.find((item) => item.id === archivingCourseId) ?? null
        : null;
    const teacherOptions = teacherOptionsState.data;
    const semesterSuggestions = useMemo(() => {
        const values = new Set<string>();
        for (const item of currentItems) {
            values.add(item.semester);
        }
        return Array.from(values).sort((left, right) => right.localeCompare(left));
    }, [currentItems]);

    const adminName = actor?.profile.full_name ?? "Administrador ADAM";
    const adminInitials = getInitials(adminName);

    const buildCourseFilters = useCallback((nextPage = page) => ({
            search: deferredSearch,
            semester: semesterFilter.trim() || undefined,
            status: statusFilter === "all" ? undefined : statusFilter,
            academic_level: academicLevelFilter === "all" ? undefined : academicLevelFilter,
            page: nextPage,
            page_size: ADMIN_PAGE_SIZE,
        }), [academicLevelFilter, deferredSearch, page, semesterFilter, statusFilter]);

    const refreshTeacherOptions = useCallback(async () => {
        setTeacherOptionsState((prev) => ({ ...prev, loading: true, error: null }));
        try {
            const data = await api.admin.getTeacherOptions();
            setTeacherOptionsState({ data, loading: false, error: null });
        } catch (error) {
            setTeacherOptionsState({
                data: null,
                loading: false,
                error: getAdminErrorMessage(error, "No se pudieron cargar las opciones de docentes para los formularios."),
            });
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        async function loadDashboard() {
            setPageLoading(true);
            setPageError(null);
            try {
                const [summaryResponse, courses] = await Promise.all([
                    api.admin.getDashboardSummary(),
                    api.admin.listCourses(buildCourseFilters()),
                ]);
                if (cancelled) return;
                setSummary(summaryResponse);
                setCoursesResponse(courses);
            } catch (error) {
                if (cancelled) return;
                setPageError(getAdminErrorMessage(error, "No se pudo cargar el dashboard administrativo."));
            } finally {
                if (!cancelled) setPageLoading(false);
            }
        }
        void loadDashboard();
        return () => {
            cancelled = true;
        };
    }, [buildCourseFilters, reloadTick]);

    useEffect(() => {
        void refreshTeacherOptions();
    }, [refreshTeacherOptions]);

    const requestExternalRefresh = useCallback(() => {
        const now = Date.now();
        if (now - lastExternalRefreshAtRef.current < 750) {
            return;
        }
        lastExternalRefreshAtRef.current = now;
        setReloadTick((prev) => prev + 1);
        void refreshTeacherOptions();
    }, [refreshTeacherOptions]);

    useEffect(() => {
        function handleWindowFocus() {
            if (document.visibilityState === "visible") {
                requestExternalRefresh();
            }
        }

        function handleVisibilityChange() {
            if (document.visibilityState === "visible") {
                requestExternalRefresh();
            }
        }

        window.addEventListener("focus", handleWindowFocus);
        document.addEventListener("visibilitychange", handleVisibilityChange);
        return () => {
            window.removeEventListener("focus", handleWindowFocus);
            document.removeEventListener("visibilitychange", handleVisibilityChange);
        };
    }, [requestExternalRefresh]);

    async function refreshSummaryAndCourses(nextPage = page) {
        const [summaryResponse, courses] = await Promise.all([
            api.admin.getDashboardSummary(),
            api.admin.listCourses(buildCourseFilters(nextPage)),
        ]);
        setSummary(summaryResponse);
        setCoursesResponse(courses);
        setPageError(null);
    }

    function openCreateModal() {
        setCourseFormError(null);
        setCreateForm(createEmptyCourseForm());
        setIsCreateOpen(true);
    }

    function openEditModal(item: AdminCourseListItem) {
        setCourseFormError(null);
        setEditingCourseId(item.id);
        setEditForm(buildCourseFormFromItem(item));
        setIsEditOpen(true);
    }

    function openArchiveModal(item: AdminCourseListItem) {
        if (item.status === "inactive") return;
        setCourseFormError(null);
        setArchivingCourseId(item.id);
        setIsArchiveOpen(true);
    }

    function openInviteModal(target: ModalInviteTarget) {
        setInviteTarget(target);
        setInviteName("");
        setInviteEmail("");
        setInviteSuccess(null);
        setInviteFormError(null);
        setIsInviteOpen(true);
    }

    function closeInviteModal() {
        setInviteSuccess(null);
        setInviteFormError(null);
        setIsInviteOpen(false);
    }

    async function handleCreateCourse(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setCourseFormError(null);
        setSubmittingCreate(true);
        try {
            const createdItem = await api.admin.createCourse(buildCoursePayload(createForm));
            const createdAccessLink = createdItem.access_link;
            if (createdAccessLink) {
                setTransientAccessLinks((prev) => ({ ...prev, [createdItem.id]: createdAccessLink }));
            }
            setIsCreateOpen(false);
            setPage(1);
            await refreshSummaryAndCourses(1);
            showToast("Curso creado correctamente.", "success");
        } catch (error) {
            setCourseFormError(getAdminErrorMessage(error, "No se pudo crear el curso."));
            if (error instanceof ApiError && error.detail === "stale_pending_teacher_invite") {
                await refreshTeacherOptions();
            }
        } finally {
            setSubmittingCreate(false);
        }
    }

    async function handleEditCourse(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!editingCourseId || !editingCourse) return;
        setCourseFormError(null);
        setSubmittingEdit(true);
        try {
            const updatedItem = await api.admin.updateCourse(editingCourseId, buildCoursePayload({ ...editForm, status: editingCourse.status }));
            const updatedAccessLink = updatedItem.access_link;
            if (updatedAccessLink) {
                setTransientAccessLinks((prev) => ({ ...prev, [updatedItem.id]: updatedAccessLink }));
            }
            await refreshSummaryAndCourses();
            setEditingCourseId(null);
            setIsEditOpen(false);
            showToast("Curso actualizado correctamente.", "success");
        } catch (error) {
            setCourseFormError(getAdminErrorMessage(error, "No se pudo actualizar el curso."));
            if (error instanceof ApiError && error.detail === "stale_pending_teacher_invite") {
                await refreshTeacherOptions();
            }
        } finally {
            setSubmittingEdit(false);
        }
    }

    async function handleArchiveCourse() {
        if (!archivingCourse) return;
        setSubmittingArchive(true);
        setCourseFormError(null);
        try {
            await api.admin.updateCourse(archivingCourse.id, {
                title: archivingCourse.title,
                code: archivingCourse.code,
                semester: archivingCourse.semester,
                academic_level: archivingCourse.academic_level,
                max_students: archivingCourse.max_students,
                status: "inactive",
                teacher_assignment: archivingCourse.teacher_assignment,
            });
            setArchivingCourseId(null);
            setIsArchiveOpen(false);
            await refreshSummaryAndCourses();
            showToast("Curso archivado correctamente.", "success");
        } catch (error) {
            const message = getAdminErrorMessage(error, "No se pudo archivar el curso.");
            setCourseFormError(message);
            showToast(message, "error");
        } finally {
            setSubmittingArchive(false);
        }
    }

    async function handleInviteTeacher(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setInviteFormError(null);
        setSubmittingInvite(true);
        try {
            const createdInvite = await api.admin.createTeacherInvite({
                full_name: inviteName.trim(),
                email: inviteEmail.trim(),
            });
            setTeacherOptionsState((prev) => ({
                data: {
                    active_teachers: prev.data?.active_teachers ?? [],
                    pending_invites: sortPendingInvites([
                        ...(prev.data?.pending_invites ?? []),
                        teacherInviteToPendingOption(createdInvite),
                    ]),
                },
                loading: false,
                error: null,
            }));
            const encodedValue = encodeTeacherOptionValue({
                kind: "pending_invite",
                invite_id: createdInvite.invite_id,
            });
            if (inviteTarget === "create") {
                setCreateForm((prev) => ({ ...prev, teacher_option_value: encodedValue }));
            } else {
                setEditForm((prev) => ({ ...prev, teacher_option_value: encodedValue }));
            }
            setInviteSuccess({
                email: createdInvite.email,
                activationLink: createdInvite.activation_link,
            });
            showToast(`Invitacion enviada a ${createdInvite.email}.`, "success");
        } catch (error) {
            setInviteFormError(getAdminErrorMessage(error, "No se pudo enviar la invitacion docente."));
        } finally {
            setSubmittingInvite(false);
        }
    }

    async function handleCopyLink(item: AdminCourseListItem) {
        const linkState = buildLinkPresentation(item, transientAccessLinks);
        if (!linkState.rawLink) {
            showToast("Este curso no tiene un enlace copiable disponible todavia.", "error");
            return;
        }
        const copied = await copyToClipboard(linkState.rawLink);
        showToast(copied ? "Enlace copiado." : "No se pudo copiar el enlace.", copied ? "success" : "error");
    }

    async function handleCopyInviteActivationLink() {
        if (!inviteSuccess) return;
        const copied = await copyToClipboard(inviteSuccess.activationLink);
        showToast(
            copied ? "Enlace de activacion copiado." : "No se pudo copiar el enlace de activacion.",
            copied ? "success" : "error",
        );
    }

    async function handleRegenerateLink(item: AdminCourseListItem) {
        setCourseFormError(null);
        setRegeneratingCourseId(item.id);
        try {
            const regenerated = await api.admin.regenerateCourseAccessLink(item.id);
            setTransientAccessLinks((prev) => ({ ...prev, [regenerated.course_id]: regenerated.access_link }));
            await refreshSummaryAndCourses();
            showToast("Enlace regenerado correctamente.", "success");
        } catch (error) {
            const message = getAdminErrorMessage(error, "No se pudo regenerar el enlace del curso.");
            setCourseFormError(message);
            showToast(message, "error");
        } finally {
            setRegeneratingCourseId(null);
        }
    }

    return (
        <div className="min-h-screen bg-[#f0f4f8] text-slate-800" data-testid="admin-dashboard-shell">
            <header className="border-b-[3px] border-[#0144a0] bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800" data-testid="admin-dashboard-header">
                <div className="mx-auto flex h-20 w-full max-w-7xl items-center justify-between gap-5 px-6">
                    <div className="flex items-center gap-3.5">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 shadow-lg">
                            <BarChart3 className="h-5 w-5 text-white" strokeWidth={2.2} />
                        </div>
                        <div>
                            <span className="text-lg font-bold tracking-tight text-white">ADAM</span>
                            <p className="mt-1 text-[11px] font-bold uppercase tracking-[0.24em] text-slate-400">Portal Administrador</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-3">
                            <div className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-white/20 bg-white/10 text-sm font-extrabold text-white">
                                {adminInitials}
                            </div>
                            <div className="hidden text-right sm:block">
                                <p className="text-[15px] font-bold leading-tight text-white">{adminName}</p>
                                <p className="mt-0.5 text-xs leading-tight text-slate-400">Admin. Institucional</p>
                                <button type="button" onClick={() => void signOut()} className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-slate-300 transition-colors hover:text-white">
                                    <LogOut className="h-3 w-3" />
                                    Cerrar sesion
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            <main className="mx-auto w-full max-w-7xl px-6 py-8">
                {pageLoading ? (
                    <DashboardLoadingState />
                ) : pageError ? (
                    <PageErrorState
                        message={pageError}
                        onRetry={() => {
                            setPageError(null);
                            setPageLoading(true);
                            setReloadTick((prev) => prev + 1);
                        }}
                    />
                ) : (
                    <>
                        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                            <KpiCard icon={<BookOpen className="h-5 w-5 text-blue-600" />} value={String(summary?.active_courses ?? 0)} label="Cursos activos" iconClassName="bg-blue-50" />
                            <KpiCard icon={<Users className="h-5 w-5 text-indigo-600" />} value={String(summary?.active_teachers ?? 0)} label="Docentes activos" iconClassName="bg-indigo-50" />
                            <KpiCard icon={<Users className="h-5 w-5 text-emerald-600" />} value={String(summary?.enrolled_students ?? 0)} label="Estudiantes matriculados" iconClassName="bg-emerald-50" />
                            <KpiCard icon={<BarChart3 className="h-5 w-5 text-amber-600" />} value={`${summary?.average_occupancy ?? 0}%`} label="Ocupacion promedio" iconClassName="bg-amber-50" />
                        </section>

                        <section className="mb-7 grid grid-cols-1 gap-4 md:grid-cols-3">
                            <ActionCard title="Crear Nuevo Curso" subtitle="Asigna un docente y genera link" onClick={openCreateModal} variant="primary" icon={<Plus className="h-5 w-5 text-white" strokeWidth={2.4} />} />
                            <ActionCard title="Gestion de Docentes" subtitle="Proximamente disponible" onClick={() => showToast("La gestion de docentes estara disponible proximamente.", "default")} variant="secondary" icon={<MailPlus className="h-5 w-5 text-slate-600" />} />
                            <ActionCard title="Reportes Globales" subtitle="Proximamente disponible" onClick={() => showToast("Modulo de reportes proximamente disponible.", "default")} variant="placeholder" icon={<ExternalLink className="h-5 w-5 text-slate-400" />} />
                        </section>

                        <section className="mb-5 flex flex-wrap items-center gap-3">
                            <div className="relative min-w-[220px] flex-1">
                                <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                                <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Buscar curso, codigo o docente..." className="w-full rounded-[11px] border-[1.5px] border-slate-200 bg-white py-3 pl-11 pr-4 text-[14.5px] text-slate-800 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10" />
                            </div>
                            <FilterTextField listId={semesterFilterListId} value={semesterFilter} onChange={(value) => { setSemesterFilter(value); setPage(1); }} options={semesterSuggestions} placeholder="Semestre (ej. 2026-I)" />
                            <FilterSelect value={statusFilter} onChange={(value) => { setStatusFilter(value); setPage(1); }} options={[{ value: "all", label: "Todos los estados" }, { value: "active", label: "Activos" }, { value: "inactive", label: "Inactivos" }]} />
                            <FilterSelect value={academicLevelFilter} onChange={(value) => { setAcademicLevelFilter(value); setPage(1); }} options={[{ value: "all", label: "Todos los niveles" }, ...ACADEMIC_LEVEL_OPTIONS.map((value) => ({ value, label: value }))]} />
                        </section>

                        <section>
                            <div className="mb-4 flex items-center gap-4">
                                <h2 className="text-xl font-bold tracking-tight text-slate-900">Directorio de Cursos</h2>
                                <div className="h-[2px] flex-1 rounded-full bg-gradient-to-r from-slate-200 to-transparent" />
                            </div>
                            <div className="overflow-hidden rounded-2xl border-[1.5px] border-slate-200 bg-white shadow-sm">
                                <div className="overflow-x-auto">
                                    <table className="w-full border-collapse text-left">
                                        <thead>
                                            <tr className="border-b border-slate-200 bg-slate-50">
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Asignatura / Codigo</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Docente Asignado</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Estado</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Capacidad</th>
                                                <th className="w-[240px] px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Link de Invitacion</th>
                                                <th className="px-5 py-3.5 text-right text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">Acciones</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-100 text-[14px] text-slate-700">
                                            {currentItems.length === 0 ? (
                                                <tr><td colSpan={6} className="px-6 py-14"><EmptyCourseState /></td></tr>
                                            ) : (
                                                currentItems.map((item) => {
                                                    const courseStatus = getCourseStatusMeta(item.status);
                                                    const teacherState = getTeacherStateMeta(item.teacher_state);
                                                    const capacityColor = getCapacityColor(item.occupancy_percent);
                                                    const linkState = buildLinkPresentation(item, transientAccessLinks);
                                                    return (
                                                        <tr key={item.id} className="group transition-colors hover:bg-slate-50/80">
                                                            <td className="px-5 py-3.5 align-middle"><CourseCell item={item} /></td>
                                                            <td className="px-5 py-3.5 align-middle"><TeacherCell item={item} teacherState={teacherState} /></td>
                                                            <td className="px-5 py-3.5 align-middle"><StatusCell courseStatus={courseStatus} /></td>
                                                            <td className="min-w-[130px] px-5 py-3.5 align-middle"><CapacityCell item={item} capacityColor={capacityColor} /></td>
                                                            <td className="px-5 py-3.5 align-middle"><LinkCell item={item} linkState={linkState} onCopy={() => void handleCopyLink(item)} /></td>
                                                            <td className="px-5 py-3.5 align-middle"><ActionsCell item={item} onEdit={() => openEditModal(item)} onArchive={() => openArchiveModal(item)} /></td>
                                                        </tr>
                                                    );
                                                })
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                                <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 bg-slate-50 px-5 py-3.5">
                                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">{summarizePageRange(coursesResponse)}</span>
                                    <Pagination currentPage={coursesResponse?.page ?? 1} totalPages={coursesResponse?.total_pages ?? 0} onPageChange={setPage} />
                                </div>
                            </div>
                        </section>
                    </>
                )}
            </main>
            <CourseModal
                isOpen={isCreateOpen}
                title="Crear Nuevo Curso"
                subtitle="Asigna un docente y genera un enlace seguro de acceso."
                form={createForm}
                onChange={setCreateForm}
                onClose={() => {
                    setCourseFormError(null);
                    setIsCreateOpen(false);
                }}
                onSubmit={handleCreateCourse}
                submitLabel={submittingCreate ? "Creando..." : "Crear curso"}
                isSubmitting={submittingCreate}
                teacherOptions={teacherOptions}
                teacherOptionsState={teacherOptionsState}
                onRetryTeacherOptions={() => { void refreshTeacherOptions(); }}
                onOpenInviteTeacher={() => openInviteModal("create")}
                formError={courseFormError}
                hideStatusMutation={false}
                activeLinkPresentation={null}
                onCopyLink={null}
                onRegenerateLink={null}
                isRegenerating={false}
            />
            <CourseModal
                isOpen={isEditOpen}
                title="Editar Curso"
                subtitle="Actualiza los datos visibles del curso sin romper el contrato del backend."
                form={editForm}
                onChange={setEditForm}
                onClose={() => {
                    setCourseFormError(null);
                    setEditingCourseId(null);
                    setIsEditOpen(false);
                }}
                onSubmit={handleEditCourse}
                submitLabel={submittingEdit ? "Guardando..." : "Guardar cambios"}
                isSubmitting={submittingEdit}
                teacherOptions={teacherOptions}
                teacherOptionsState={teacherOptionsState}
                onRetryTeacherOptions={() => { void refreshTeacherOptions(); }}
                onOpenInviteTeacher={() => openInviteModal("edit")}
                formError={courseFormError}
                hideStatusMutation
                activeLinkPresentation={editingCourse ? buildLinkPresentation(editingCourse, transientAccessLinks) : null}
                onCopyLink={editingCourse ? (() => void handleCopyLink(editingCourse)) : null}
                onRegenerateLink={editingCourse ? (() => void handleRegenerateLink(editingCourse)) : null}
                isRegenerating={regeneratingCourseId === editingCourse?.id}
            />
            <ConfirmationModal
                isOpen={isArchiveOpen}
                title="Archivar Curso"
                description={archivingCourse ? `El curso "${archivingCourse.title}" pasara a estado inactivo. No se eliminara informacion, pero el dashboard dejara de tratarlo como curso activo.` : ""}
                confirmLabel={submittingArchive ? "Archivando..." : "Archivar curso"}
                isSubmitting={submittingArchive}
                onClose={() => {
                    setCourseFormError(null);
                    setArchivingCourseId(null);
                    setIsArchiveOpen(false);
                }}
                onConfirm={() => void handleArchiveCourse()}
            />
            <InviteTeacherModal
                isOpen={isInviteOpen}
                fullName={inviteName}
                email={inviteEmail}
                error={inviteFormError}
                success={inviteSuccess}
                isSubmitting={submittingInvite}
                onChangeFullName={setInviteName}
                onChangeEmail={setInviteEmail}
                onClose={closeInviteModal}
                onSubmit={handleInviteTeacher}
                onCopyActivationLink={() => void handleCopyInviteActivationLink()}
                onInviteAnother={() => {
                    setInviteSuccess(null);
                    setInviteName("");
                    setInviteEmail("");
                    setInviteFormError(null);
                }}
            />
        </div>
    );
}

function KpiCard({
    icon,
    value,
    label,
    iconClassName,
}: {
    icon: ReactNode;
    value: string;
    label: string;
    iconClassName: string;
}) {
    return (
        <article className="flex items-center gap-3.5 rounded-2xl border-[1.5px] border-slate-200 bg-white px-5 py-5 shadow-[0_1px_4px_rgba(0,0,0,0.04)] transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-[0_4px_14px_rgba(1,68,160,0.08)]">
            <div className={`flex h-[46px] w-[46px] items-center justify-center rounded-xl ${iconClassName}`}>{icon}</div>
            <div>
                <p className="text-2xl font-bold text-slate-900">{value}</p>
                <p className="text-xs font-medium text-slate-500">{label}</p>
            </div>
        </article>
    );
}

function ActionCard({
    title,
    subtitle,
    onClick,
    variant,
    icon,
}: {
    title: string;
    subtitle: string;
    onClick: () => void;
    variant: "primary" | "secondary" | "placeholder";
    icon: ReactNode;
}) {
    const classes = variant === "primary"
        ? "border-transparent bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white shadow-lg hover:-translate-y-1 hover:shadow-xl"
        : variant === "secondary"
            ? "border-[1.5px] border-slate-200 bg-white text-slate-800 hover:-translate-y-1 hover:border-blue-300 hover:shadow-lg"
            : "border-[1.5px] border-dashed border-slate-300 bg-white text-slate-500 opacity-70 hover:-translate-y-1 hover:border-blue-200 hover:opacity-100";
    const iconClasses = variant === "primary"
        ? "border border-white/20 bg-white/10 text-white"
        : variant === "secondary"
            ? "border border-slate-100 bg-slate-50 text-slate-600"
            : "border border-dashed border-slate-200 bg-slate-50 text-slate-400";
    const subtitleClass = variant === "primary" ? "text-blue-200" : "text-slate-500";

    return (
        <button type="button" onClick={onClick} className={`group relative flex h-[90px] cursor-pointer flex-col justify-center overflow-hidden rounded-2xl px-5 text-left transition-all duration-200 ${classes}`}>
            <div className="relative z-10 flex items-center justify-between">
                <div>
                    <h3 className="text-[16px] font-bold tracking-tight">{title}</h3>
                    <p className={`mt-1 text-xs font-medium ${subtitleClass}`}>{subtitle}</p>
                </div>
                <div className={`flex h-11 w-11 items-center justify-center rounded-xl backdrop-blur-sm ${iconClasses}`}>{icon}</div>
            </div>
        </button>
    );
}

function FilterSelect({
    value,
    onChange,
    options,
}: {
    value: string;
    onChange: (value: string) => void;
    options: Array<{ value: string; label: string }>;
}) {
    return (
        <select value={value} onChange={(event) => onChange(event.target.value)} className="min-w-[160px] rounded-[11px] border-[1.5px] border-slate-200 bg-white px-4 py-3 pr-10 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10">
            {options.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
            ))}
        </select>
    );
}

function FilterTextField({
    listId,
    value,
    onChange,
    options,
    placeholder,
}: {
    listId: string;
    value: string;
    onChange: (value: string) => void;
    options: string[];
    placeholder: string;
}) {
    return (
        <div className="min-w-[180px]">
            <input list={listId} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full rounded-[11px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10" />
            <datalist id={listId}>{options.map((option) => <option key={option} value={option} />)}</datalist>
        </div>
    );
}

function CourseCell({ item }: { item: AdminCourseListItem }) {
    return (
        <>
            <p className="mb-1 line-clamp-1 text-[14px] font-bold text-slate-800" title={item.title}>{item.title}</p>
            <div className="flex items-center gap-2">
                <span className="inline-flex rounded-[7px] bg-[#e8f0fe] px-2.5 py-1 text-[11.5px] font-semibold text-[#0144a0]">{item.code}</span>
                <span className="text-[11px] font-medium text-slate-400">{item.semester} · {item.academic_level}</span>
            </div>
        </>
    );
}

function TeacherCell({
    item,
    teacherState,
}: {
    item: AdminCourseListItem;
    teacherState: ReturnType<typeof getTeacherStateMeta>;
}) {
    return (
        <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-slate-600">{getInitials(item.teacher_display_name)}</div>
            <div className="min-w-0">
                <span className="block truncate text-sm font-semibold text-slate-700">{item.teacher_display_name}</span>
                <span className={`mt-1 inline-flex rounded-[7px] px-2 py-1 text-[11px] font-semibold ${teacherState.classes}`}>{teacherState.label}</span>
            </div>
        </div>
    );
}

function StatusCell({
    courseStatus,
}: {
    courseStatus: ReturnType<typeof getCourseStatusMeta>;
}) {
    return (
        <span className={`inline-flex items-center gap-2 rounded-[7px] px-2.5 py-1 text-[11.5px] font-semibold ${courseStatus.classes}`}>
            <span className={`h-[7px] w-[7px] rounded-full ${courseStatus.dot}`} />
            {courseStatus.label}
        </span>
    );
}

function CapacityCell({
    item,
    capacityColor,
}: {
    item: AdminCourseListItem;
    capacityColor: string;
}) {
    return (
        <>
            <div className="mb-1 flex items-center gap-1">
                <Users className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="text-sm font-bold text-slate-700">{item.students_count}</span>
                <span className="text-sm font-normal text-slate-400">/ {item.max_students}</span>
                <span className="ml-1 text-[11px] font-bold" style={{ color: capacityColor }}>{item.occupancy_percent}%</span>
            </div>
            <div className="h-[5px] overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full transition-[width]" style={{ width: `${item.occupancy_percent}%`, background: capacityColor }} />
            </div>
        </>
    );
}

function LinkCell({
    item,
    linkState,
    onCopy,
}: {
    item: AdminCourseListItem;
    linkState: LinkPresentation;
    onCopy: () => void;
}) {
    return (
        <>
            <div className="rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex items-center overflow-hidden">
                    <span className="min-w-0 flex-1 truncate px-3 py-2 font-mono text-[12.5px] text-slate-600" title={linkState.text}>{linkState.text}</span>
                    <button type="button" onClick={onCopy} disabled={!linkState.rawLink} className="border-l border-slate-300 bg-slate-200 px-2.5 py-2 text-slate-700 transition hover:bg-slate-300 disabled:cursor-not-allowed disabled:opacity-50" aria-label={`Copiar enlace de ${item.title}`}>
                        <Copy className="h-4 w-4" />
                    </button>
                </div>
            </div>
            <p className="mt-2 text-xs text-slate-400">{linkState.helper}</p>
        </>
    );
}

function ActionsCell({
    item,
    onEdit,
    onArchive,
}: {
    item: AdminCourseListItem;
    onEdit: () => void;
    onArchive: () => void;
}) {
    return (
        <div className="flex items-center justify-end gap-1 opacity-70 transition-opacity group-hover:opacity-100">
            <button type="button" onClick={onEdit} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-blue-50 hover:text-[#0144a0]" aria-label={`Editar ${item.title}`}>
                <Pencil className="h-5 w-5" />
            </button>
            <button type="button" disabled={item.status === "inactive"} onClick={onArchive} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40" aria-label={`Archivar ${item.title}`}>
                <Archive className="h-5 w-5" />
            </button>
        </div>
    );
}

function Pagination({
    currentPage,
    totalPages,
    onPageChange,
}: {
    currentPage: number;
    totalPages: number;
    onPageChange: (page: number) => void;
}) {
    if (totalPages <= 1) return null;

    return (
        <div className="flex items-center gap-1.5" data-testid="admin-dashboard-pagination">
            <PageButton disabled={currentPage === 1} onClick={() => onPageChange(currentPage - 1)}>‹</PageButton>
            {Array.from({ length: totalPages }, (_, index) => index + 1).map((nextPage) => (
                <PageButton key={nextPage} active={nextPage === currentPage} onClick={() => onPageChange(nextPage)}>{nextPage}</PageButton>
            ))}
            <PageButton disabled={currentPage === totalPages} onClick={() => onPageChange(currentPage + 1)}>›</PageButton>
        </div>
    );
}

function PageButton({
    children,
    onClick,
    active = false,
    disabled = false,
}: {
    children: ReactNode;
    onClick: () => void;
    active?: boolean;
    disabled?: boolean;
}) {
    return (
        <button type="button" disabled={disabled} onClick={onClick} className={`flex h-8 w-8 items-center justify-center rounded-lg border-[1.5px] text-[13px] font-semibold transition ${active ? "border-[#0144a0] bg-[#0144a0] text-white" : "border-slate-200 bg-white text-slate-600 hover:border-[#0144a0] hover:bg-[#e8f0fe] hover:text-[#0144a0]"} disabled:cursor-not-allowed disabled:opacity-40`}>
            {children}
        </button>
    );
}

function DashboardLoadingState() {
    return (
        <div className="space-y-6" data-testid="admin-dashboard-loading">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-[86px] animate-pulse rounded-2xl border border-slate-200 bg-white" />)}
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => <div key={index} className="h-[90px] animate-pulse rounded-2xl border border-slate-200 bg-white" />)}
            </div>
            <div className="h-[420px] animate-pulse rounded-2xl border border-slate-200 bg-white" />
        </div>
    );
}

function PageErrorState({
    message,
    onRetry,
}: {
    message: string;
    onRetry: () => void;
}) {
    return (
        <div className="flex min-h-[520px] items-center justify-center" data-testid="global-page-error">
            <div className="max-w-xl rounded-3xl border border-red-200 bg-white px-8 py-10 text-center shadow-sm">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50 text-red-600">
                    <TriangleAlert className="h-7 w-7" />
                </div>
                <h1 className="mt-5 text-2xl font-bold tracking-tight text-slate-900">No se pudo cargar el dashboard</h1>
                <p className="mt-3 text-sm leading-6 text-slate-500">{message}</p>
                <button type="button" onClick={onRetry} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-5 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-[#00337a]">Reintentar</button>
            </div>
        </div>
    );
}

function EmptyCourseState() {
    return (
        <div className="flex flex-col items-center gap-3 text-center" data-testid="admin-dashboard-empty">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100">
                <BookOpen className="h-6 w-6 text-slate-400" />
            </div>
            <p className="text-sm font-semibold text-slate-500">No se encontraron cursos</p>
            <p className="text-xs text-slate-400">Ajusta los filtros o crea un nuevo curso para comenzar.</p>
        </div>
    );
}

function CourseModal({
    isOpen,
    title,
    subtitle,
    form,
    onChange,
    onClose,
    onSubmit,
    submitLabel,
    isSubmitting,
    teacherOptions,
    teacherOptionsState,
    onRetryTeacherOptions,
    onOpenInviteTeacher,
    formError,
    hideStatusMutation,
    activeLinkPresentation,
    onCopyLink,
    onRegenerateLink,
    isRegenerating,
}: {
    isOpen: boolean;
    title: string;
    subtitle: string;
    form: CourseFormState;
    onChange: Dispatch<SetStateAction<CourseFormState>>;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    submitLabel: string;
    isSubmitting: boolean;
    teacherOptions: AdminTeacherOptionsResponse | null;
    teacherOptionsState: TeacherOptionsState;
    onRetryTeacherOptions: () => void;
    onOpenInviteTeacher: () => void;
    formError: string | null;
    hideStatusMutation: boolean;
    activeLinkPresentation: LinkPresentation | null;
    onCopyLink: (() => void) | null;
    onRegenerateLink: (() => void) | null;
    isRegenerating: boolean;
}) {
    const teacherFieldId = useId();
    const teacherOptionsBlocked = teacherOptionsState.loading || Boolean(teacherOptionsState.error);
    const modalTestId = title.toLowerCase().includes("crear") ? "create-course-modal" : "edit-course-modal";

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-2xl overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]" data-testid={modalTestId}>
                <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
                    <div>
                        <h2 className="text-xl font-bold tracking-tight text-slate-900">{title}</h2>
                        <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
                    </div>
                    <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 transition hover:text-slate-700" aria-label="Cerrar modal">
                        <X className="h-5 w-5" />
                    </button>
                </div>
                <form onSubmit={onSubmit} className="space-y-5 px-6 py-6">
                    <div className="grid gap-5 md:grid-cols-2">
                        <Field label="Nombre del curso" value={form.title} onChange={(value) => onChange((prev) => ({ ...prev, title: value }))} placeholder="Ej. Finanzas Corporativas" />
                        <Field label="Codigo" value={form.code} onChange={(value) => onChange((prev) => ({ ...prev, code: value }))} placeholder="FIN-401" />
                        <Field label="Semestre" value={form.semester} onChange={(value) => onChange((prev) => ({ ...prev, semester: value }))} placeholder="2026-I" />
                        <SelectField label="Nivel academico" value={form.academic_level} onChange={(value) => onChange((prev) => ({ ...prev, academic_level: value }))} options={ACADEMIC_LEVEL_OPTIONS.map((value) => ({ value, label: value }))} />
                        <Field label="Capacidad maxima" type="number" min={1} value={form.max_students} onChange={(value) => onChange((prev) => ({ ...prev, max_students: value }))} placeholder="30" />
                        <SelectField label="Estado" value={form.status} onChange={(value) => onChange((prev) => ({ ...prev, status: value as AdminCourseStatus }))} options={COURSE_STATUS_OPTIONS} disabled={hideStatusMutation} helper={hideStatusMutation ? "El estado se cambia desde la accion Archivar para evitar restores accidentales." : undefined} />
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between gap-3">
                            <label htmlFor={teacherFieldId} className="text-sm font-bold text-slate-700">Docente asignado</label>
                            <button type="button" onClick={onOpenInviteTeacher} className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-[12px] font-bold text-[#0144a0] transition hover:text-[#00337a]">
                                <MailPlus className="h-3.5 w-3.5" />
                                Invitar docente
                            </button>
                        </div>
                        {teacherOptionsBlocked ? (
                            <TeacherOptionsErrorState loading={teacherOptionsState.loading} error={teacherOptionsState.error} onRetry={onRetryTeacherOptions} />
                        ) : (
                            <select id={teacherFieldId} value={form.teacher_option_value} onChange={(event) => onChange((prev) => ({ ...prev, teacher_option_value: event.target.value }))} className="w-full rounded-[9px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10">
                                <option value="">Selecciona un docente</option>
                                {(teacherOptions?.active_teachers.length ?? 0) > 0 && (
                                    <optgroup label="Docentes activos">
                                        {teacherOptions?.active_teachers.map((option) => (
                                            <option key={option.membership_id} value={`membership:${option.membership_id}`}>{option.full_name} ({option.email})</option>
                                        ))}
                                    </optgroup>
                                )}
                                {(teacherOptions?.pending_invites.length ?? 0) > 0 && (
                                    <optgroup label="Invitaciones pendientes">
                                        {teacherOptions?.pending_invites.map((option) => (
                                            <option key={option.invite_id} value={`pending_invite:${option.invite_id}`}>{option.full_name} ({option.email}) - Pendiente</option>
                                        ))}
                                    </optgroup>
                                )}
                            </select>
                        )}
                    </div>

                    {activeLinkPresentation && (
                        <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4">
                            <div className="flex items-center justify-between gap-3">
                                <label className="text-sm font-bold text-slate-700">Link de invitacion</label>
                                <div className="flex items-center gap-2">
                                    <button type="button" onClick={onCopyLink ?? undefined} disabled={!activeLinkPresentation.rawLink} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                                        <Copy className="h-4 w-4" />
                                        Copiar
                                    </button>
                                    <button type="button" onClick={onRegenerateLink ?? undefined} disabled={!activeLinkPresentation.canRegenerate || isRegenerating} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50">
                                        Regenerar enlace
                                    </button>
                                </div>
                            </div>
                            <div className="rounded-lg border border-slate-200 bg-white">
                                <div className="truncate px-3 py-2 font-mono text-[12.5px] text-slate-600" title={activeLinkPresentation.text}>{activeLinkPresentation.text}</div>
                            </div>
                            <p className="text-xs text-slate-400">{activeLinkPresentation.helper} Regenerar invalida el enlace anterior.</p>
                        </div>
                    )}

                    {formError && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{formError}</div>}

                    <div className="flex items-center justify-end gap-3 border-t border-slate-200 pt-5">
                        <button type="button" onClick={onClose} className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900">Cancelar</button>
                        <button type="submit" disabled={isSubmitting || teacherOptionsBlocked} className="inline-flex items-center justify-center rounded-xl bg-[#0144a0] px-5 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50">{submitLabel}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}

function TeacherOptionsErrorState({
    loading,
    error,
    onRetry,
}: {
    loading: boolean;
    error: string | null;
    onRetry: () => void;
}) {
    return (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="text-sm font-semibold text-amber-900">{loading ? "Cargando selector de docentes..." : "No se pudo cargar el selector de docentes"}</p>
            {error && <p className="mt-1 text-sm text-amber-800">{error}</p>}
            {!loading && <button type="button" onClick={onRetry} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-semibold text-amber-900 transition hover:bg-amber-100">Reintentar</button>}
        </div>
    );
}

function ConfirmationModal({
    isOpen,
    title,
    description,
    confirmLabel,
    isSubmitting,
    onClose,
    onConfirm,
}: {
    isOpen: boolean;
    title: string;
    description: string;
    confirmLabel: string;
    isSubmitting: boolean;
    onClose: () => void;
    onConfirm: () => void;
}) {
    if (!isOpen) return null;
    return (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]">
                <div className="px-6 py-5">
                    <h2 className="text-xl font-bold tracking-tight text-slate-900">{title}</h2>
                    <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
                </div>
                <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
                    <button type="button" onClick={onClose} className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900">Cancelar</button>
                    <button type="button" onClick={onConfirm} disabled={isSubmitting} className="inline-flex items-center justify-center rounded-xl bg-red-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50">{confirmLabel}</button>
                </div>
            </div>
        </div>
    );
}

function InviteTeacherModal({
    isOpen,
    fullName,
    email,
    error,
    success,
    isSubmitting,
    onChangeFullName,
    onChangeEmail,
    onClose,
    onSubmit,
    onCopyActivationLink,
    onInviteAnother,
}: {
    isOpen: boolean;
    fullName: string;
    email: string;
    error: string | null;
    success: InviteSuccessState | null;
    isSubmitting: boolean;
    onChangeFullName: (value: string) => void;
    onChangeEmail: (value: string) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onCopyActivationLink: () => void;
    onInviteAnother: () => void;
}) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]">
                <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
                    <div>
                        <h2 className="text-xl font-bold tracking-tight text-slate-900">Invitar Docente</h2>
                        <p className="mt-1 text-sm text-slate-500">Crea una invitacion pendiente para asignarla a cursos antes del registro.</p>
                    </div>
                    <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 transition hover:text-slate-700" aria-label="Cerrar modal de invitacion">
                        <X className="h-5 w-5" />
                    </button>
                </div>
                {success ? (
                    <div className="space-y-4 px-6 py-6" data-testid="teacher-invite-success">
                        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">Invitacion creada para <strong>{success.email}</strong>.</div>
                        <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4">
                            <label className="text-sm font-bold text-slate-700">Enlace de activacion</label>
                            <div className="rounded-lg border border-slate-200 bg-white">
                                <div className="truncate px-3 py-2 font-mono text-[12.5px] text-slate-600" title={success.activationLink}>{success.activationLink}</div>
                            </div>
                            <div className="flex items-center justify-end gap-2">
                                <button type="button" onClick={onInviteAnother} className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900">Invitar otro</button>
                                <button type="button" onClick={onCopyActivationLink} className="inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#00337a]">
                                    <Copy className="h-4 w-4" />
                                    Copiar enlace
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <form onSubmit={onSubmit} className="space-y-4 px-6 py-6">
                        <Field label="Nombre completo" value={fullName} onChange={onChangeFullName} placeholder="Ej. Laura Gomez" />
                        <Field label="Correo institucional" value={email} onChange={onChangeEmail} placeholder="laura.gomez@universidad.edu" type="email" />
                        {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
                        <div className="flex items-center justify-end gap-3 border-t border-slate-200 pt-5">
                            <button type="button" onClick={onClose} className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900">Cancelar</button>
                            <button type="submit" disabled={isSubmitting} className="inline-flex items-center justify-center rounded-xl bg-[#0144a0] px-5 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50">{isSubmitting ? "Enviando..." : "Enviar invitacion"}</button>
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}

function Field({
    label,
    value,
    onChange,
    placeholder,
    type = "text",
    min,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    type?: HTMLInputTypeAttribute;
    min?: number;
}) {
    const inputId = useId();
    return (
        <label className="block space-y-1.5">
            <span className="text-sm font-bold text-slate-700" id={`${inputId}-label`}>{label}</span>
            <input id={inputId} aria-labelledby={`${inputId}-label`} type={type} min={min} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full rounded-[9px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10" />
        </label>
    );
}

function SelectField({
    label,
    value,
    onChange,
    options,
    disabled = false,
    helper,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: ReadonlyArray<{ value: string; label: string }>;
    disabled?: boolean;
    helper?: string;
}) {
    const selectId = useId();
    return (
        <label className="block space-y-1.5">
            <span className="text-sm font-bold text-slate-700" id={`${selectId}-label`}>{label}</span>
            <select id={selectId} aria-labelledby={`${selectId}-label`} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="w-full rounded-[9px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500">
                {options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                ))}
            </select>
            {helper && <p className="text-xs text-slate-400">{helper}</p>}
        </label>
    );
}

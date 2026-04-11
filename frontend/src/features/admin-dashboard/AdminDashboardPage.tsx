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
    Check,
    GraduationCap,
} from "lucide-react";
import {
    memo,
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
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectLabel,
    SelectTrigger,
    SelectValue,
} from "@/shared/ui/select";
import {
    ADMIN_PAGE_SIZE,
    ACADEMIC_LEVEL_OPTIONS,
    SEMESTER_TERM_OPTIONS,
    COURSE_STATUS_OPTIONS,
    EMPTY_COURSES,
    buildSemesterYearOptions,
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
    reconcileCourseListResponse,
    reconcileDashboardSummary,
    sortPendingInvites,
    summarizePageRange,
    teacherInviteToPendingOption,
    type CourseFormState,
    type LinkPresentation,
    type SemesterTerm,
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

type RefreshMode = "initial" | "background";
const ALL_FILTER_VALUE = "all";
const UI_UNSET_SELECT_VALUE = "__unset_select_value__";
const UI_UNASSIGNED_TEACHER_VALUE = "__unassigned_teacher_value__";

export function AdminDashboardPage({ showToast }: Props) {
    const { actor, signOut } = useAuth();

    const [summary, setSummary] = useState<AdminDashboardSummaryResponse | null>(null);
    const [coursesResponse, setCoursesResponse] = useState<AdminCourseListResponse | null>(null);
    const [isInitialLoading, setIsInitialLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [pageError, setPageError] = useState<string | null>(null);
    const [refreshError, setRefreshError] = useState<string | null>(null);
    const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
    const [teacherOptionsState, setTeacherOptionsState] = useState<TeacherOptionsState>({
        data: null,
        isInitialLoading: false,
        isRefreshing: false,
        error: null,
    });
    const [transientAccessLinks, setTransientAccessLinks] = useState<Record<string, string>>({});
    const [search, setSearch] = useState("");
    const deferredSearch = useDeferredValue(search);
    const [semesterFilter, setSemesterFilter] = useState(ALL_FILTER_VALUE);
    const [statusFilter, setStatusFilter] = useState(ALL_FILTER_VALUE);
    const [academicLevelFilter, setAcademicLevelFilter] = useState(ALL_FILTER_VALUE);
    const [page, setPage] = useState(1);
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
    const isMountedRef = useRef(true);
    const didLoadDashboardRef = useRef(false);
    const didLoadTeacherOptionsRef = useRef(false);
    const dashboardRequestIdRef = useRef(0);
    const teacherOptionsRequestIdRef = useRef(0);
    const lastExternalRefreshAtRef = useRef(0);

    useEffect(() => {
        isMountedRef.current = true;
        return () => {
            isMountedRef.current = false;
        };
    }, []);

    const currentItems = useMemo(() => coursesResponse?.items ?? EMPTY_COURSES, [coursesResponse]);
    const hasDashboardData = summary !== null && coursesResponse !== null;
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
    const semesterYearOptions = useMemo(() => buildSemesterYearOptions(), []);

    const adminName = actor?.profile.full_name ?? "Administrador ADAM";
    const adminInitials = getInitials(adminName);

    const buildCourseFilters = useCallback((nextPage = page) => ({
            search: deferredSearch,
            semester: semesterFilter === ALL_FILTER_VALUE ? undefined : semesterFilter,
            status: statusFilter === ALL_FILTER_VALUE ? undefined : statusFilter,
            academic_level: academicLevelFilter === ALL_FILTER_VALUE ? undefined : academicLevelFilter,
            page: nextPage,
            page_size: ADMIN_PAGE_SIZE,
        }), [academicLevelFilter, deferredSearch, page, semesterFilter, statusFilter]);

    const applyDashboardSnapshot = useCallback((
        summaryResponse: AdminDashboardSummaryResponse,
        courses: AdminCourseListResponse,
    ) => {
        didLoadDashboardRef.current = true;
        setSummary((prev) => reconcileDashboardSummary(prev, summaryResponse));
        setCoursesResponse((prev) => reconcileCourseListResponse(prev, courses));
        setPageError(null);
        setRefreshError(null);
        setLastSyncedAt(Date.now());
    }, []);

    const refreshTeacherOptions = useCallback(async ({ mode }: { mode?: RefreshMode } = {}) => {
        const requestId = ++teacherOptionsRequestIdRef.current;
        const refreshMode = mode ?? (didLoadTeacherOptionsRef.current ? "background" : "initial");
        const isBlocking = refreshMode === "initial" && !didLoadTeacherOptionsRef.current;

        setTeacherOptionsState((prev) => ({
            data: prev.data,
            isInitialLoading: isBlocking,
            isRefreshing: !isBlocking && prev.data !== null,
            error: isBlocking ? null : prev.error,
        }));

        try {
            const data = await api.admin.getTeacherOptions();
            if (!isMountedRef.current || requestId !== teacherOptionsRequestIdRef.current) {
                return data;
            }

            didLoadTeacherOptionsRef.current = true;
            setTeacherOptionsState({
                data,
                isInitialLoading: false,
                isRefreshing: false,
                error: null,
            });
            return data;
        } catch (error) {
            if (!isMountedRef.current || requestId !== teacherOptionsRequestIdRef.current) {
                throw error;
            }

            setTeacherOptionsState((prev) => ({
                data: prev.data,
                isInitialLoading: false,
                isRefreshing: false,
                error: getAdminErrorMessage(error, "No se pudieron cargar las opciones de docentes para los formularios."),
            }));
            throw error;
        }
    }, []);

    const refreshDashboard = useCallback(async (
        { nextPage = page, mode }: { nextPage?: number; mode?: RefreshMode } = {},
    ) => {
        const requestId = ++dashboardRequestIdRef.current;
        const refreshMode = mode ?? (didLoadDashboardRef.current ? "background" : "initial");
        const isBlocking = refreshMode === "initial" && !didLoadDashboardRef.current;

        if (isBlocking) {
            setIsInitialLoading(true);
            setPageError(null);
        } else {
            setIsRefreshing(true);
            setRefreshError(null);
        }

        try {
            const [summaryResponse, courses] = await Promise.all([
                api.admin.getDashboardSummary(),
                api.admin.listCourses(buildCourseFilters(nextPage)),
            ]);
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) {
                return;
            }

            applyDashboardSnapshot(summaryResponse, courses);
        } catch (error) {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) {
                throw error;
            }

            const message = getAdminErrorMessage(error, "No se pudo cargar el dashboard administrativo.");
            if (isBlocking) {
                setPageError(message);
            } else {
                setRefreshError(message);
            }
            throw error;
        } finally {
            if (isMountedRef.current && requestId === dashboardRequestIdRef.current) {
                if (isBlocking) {
                    setIsInitialLoading(false);
                } else {
                    setIsRefreshing(false);
                }
            }
        }
    }, [applyDashboardSnapshot, buildCourseFilters, page]);

    useEffect(() => {
        void refreshDashboard().catch(() => undefined);
    }, [refreshDashboard]);

    useEffect(() => {
        void refreshTeacherOptions({ mode: "initial" }).catch(() => undefined);
    }, [refreshTeacherOptions]);

    const requestExternalRefresh = useCallback(() => {
        if (!didLoadDashboardRef.current) {
            return;
        }

        const now = Date.now();
        if (now - lastExternalRefreshAtRef.current < 750) {
            return;
        }
        lastExternalRefreshAtRef.current = now;
        void refreshDashboard({ mode: "background" }).catch(() => undefined);
        void refreshTeacherOptions({ mode: "background" }).catch(() => undefined);
    }, [refreshDashboard, refreshTeacherOptions]);

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

    const refreshSummaryAndCourses = useCallback(async (nextPage = page) => {
        await refreshDashboard({
            nextPage,
            mode: didLoadDashboardRef.current ? "background" : "initial",
        });
    }, [page, refreshDashboard]);

    const openCreateModal = useCallback(() => {
        setCourseFormError(null);
        setCreateForm(createEmptyCourseForm());
        setIsCreateOpen(true);
    }, []);

    const openEditModal = useCallback((item: AdminCourseListItem) => {
        setCourseFormError(null);
        setEditingCourseId(item.id);
        setEditForm(buildCourseFormFromItem(item));
        setIsEditOpen(true);
    }, []);

    const openArchiveModal = useCallback((item: AdminCourseListItem) => {
        if (item.status === "inactive") return;
        setCourseFormError(null);
        setArchivingCourseId(item.id);
        setIsArchiveOpen(true);
    }, []);

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
                isInitialLoading: false,
                isRefreshing: false,
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

    const handleCopyLink = useCallback(async (item: AdminCourseListItem) => {
        const linkState = buildLinkPresentation(item, transientAccessLinks);
        if (!linkState.rawLink) {
            showToast("Este curso no tiene un enlace copiable disponible todavia.", "error");
            return;
        }
        const copied = await copyToClipboard(linkState.rawLink);
        showToast(copied ? "Enlace copiado." : "No se pudo copiar el enlace.", copied ? "success" : "error");
    }, [showToast, transientAccessLinks]);

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
                {!hasDashboardData && isInitialLoading ? (
                    <DashboardLoadingState />
                ) : !hasDashboardData && pageError ? (
                    <PageErrorState
                        message={pageError}
                        onRetry={() => {
                            void refreshDashboard({ mode: "initial" }).catch(() => undefined);
                        }}
                    />
                ) : (
                    <>
                        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                            <KpiCard icon={<BookOpen className="h-5 w-5 text-blue-600" />} value={String(summary?.active_courses ?? 0)} label="Cursos activos" iconClassName="bg-blue-50" />
                            <KpiCard icon={<Users className="h-5 w-5 text-indigo-600" />} value={String(summary?.active_teachers ?? 0)} label="Docentes activos" iconClassName="bg-indigo-50" />
                            <KpiCard icon={<GraduationCap className="h-5 w-5 text-emerald-600" />} value={String(summary?.enrolled_students ?? 0)} label="Estudiantes matriculados" iconClassName="bg-emerald-50" />
                            <KpiCard icon={<BarChart3 className="h-5 w-5 text-amber-600" />} value={`${summary?.average_occupancy ?? 0}%`} label="Ocupacion promedio" iconClassName="bg-amber-50" />
                        </section>

                        <section className="mb-7 grid grid-cols-1 gap-4 md:grid-cols-3">
                            <ActionCard title="Crear Nuevo Curso" subtitle="Asigna un docente y genera link" onClick={openCreateModal} variant="primary" icon={<Plus className="h-5 w-5 text-white" strokeWidth={2.4} />} />
                            <ActionCard title="Gestion de Docentes" subtitle="Proximamente disponible" onClick={() => showToast("La gestion de docentes estara disponible proximamente.", "default")} variant="primary" icon={<Users className="h-5 w-5 text-white" strokeWidth={2.4} />} />
                            <ActionCard title="Reportes Globales" subtitle="Proximamente disponible" onClick={() => showToast("Modulo de reportes proximamente disponible.", "default")} variant="placeholder" icon={<ExternalLink className="h-5 w-5 text-slate-400" />} />
                        </section>

                        <section className="mb-5 flex flex-wrap items-center gap-3">
                            <div className="relative min-w-[220px] flex-1">
                                <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                                <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Buscar curso, codigo o docente..." className="w-full rounded-[11px] border-[1.5px] border-slate-200 bg-white py-3 pl-11 pr-4 text-[14.5px] text-slate-800 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10" />
                            </div>
                            <FilterSelect
                                ariaLabel="Filtrar por semestre"
                                value={semesterFilter}
                                onChange={(value) => { setSemesterFilter(value); setPage(1); }}
                                options={[
                                    { value: ALL_FILTER_VALUE, label: "Todos los semestres" },
                                    ...semesterSuggestions.map((value) => ({ value, label: value })),
                                ]}
                            />
                            <FilterSelect ariaLabel="Filtrar por estado" value={statusFilter} onChange={(value) => { setStatusFilter(value); setPage(1); }} options={[{ value: ALL_FILTER_VALUE, label: "Todos los estados" }, { value: "active", label: "Activos" }, { value: "inactive", label: "Inactivos" }]} />
                            <FilterSelect ariaLabel="Filtrar por nivel academico" value={academicLevelFilter} onChange={(value) => { setAcademicLevelFilter(value); setPage(1); }} options={[{ value: ALL_FILTER_VALUE, label: "Todos los niveles" }, ...ACADEMIC_LEVEL_OPTIONS.map((value) => ({ value, label: value }))]} />
                        </section>

                        <section>
                            <div className="mb-4 flex items-center gap-4">
                                <h2 className="text-xl font-bold tracking-tight text-slate-900">Directorio de Cursos</h2>
                                <DashboardRefreshStatus
                                    isRefreshing={isRefreshing}
                                    refreshError={refreshError}
                                    lastSyncedAt={lastSyncedAt}
                                    onRetry={() => {
                                        void refreshDashboard({ mode: "background" }).catch(() => undefined);
                                    }}
                                />
                                <div className="h-[2px] flex-1 rounded-full bg-gradient-to-r from-slate-200 to-transparent" />
                            </div>
                            <div className="overflow-hidden rounded-2xl border-[1.5px] border-slate-200 bg-white shadow-sm">
                                <div className="overflow-x-auto">
                                    <table className="w-full border-collapse text-left">
                                        <thead>
                                            <tr className="border-b border-slate-200 bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800">
                                                <th className="px-5 py-3.5 text-right text-[12px] font-bold uppercase tracking-[0.18em] text-white">Acciones</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-white">Asignatura / Codigo</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-white">Docente Asignado</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-white">Estado</th>
                                                <th className="px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-white">Capacidad</th>
                                                <th className="w-[240px] px-5 py-3.5 text-[12px] font-bold uppercase tracking-[0.18em] text-white">Link de Invitacion</th>        
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-100 text-[14px] text-slate-700">
                                            {currentItems.length === 0 ? (
                                                <tr><td colSpan={6} className="px-6 py-14"><EmptyCourseState /></td></tr>
                                            ) : (
                                                currentItems.map((item) => (
                                                    <CourseRow
                                                        key={item.id}
                                                        item={item}
                                                        transientAccessLink={transientAccessLinks[item.id]}
                                                        onCopy={handleCopyLink}
                                                        onRegenerate={handleRegenerateLink}
                                                        isRegenerating={regeneratingCourseId === item.id}
                                                        onEdit={openEditModal}
                                                        onArchive={openArchiveModal}
                                                    />
                                                ))
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
                semesterYearOptions={semesterYearOptions}
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
                semesterYearOptions={semesterYearOptions}
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
    ariaLabel,
    value,
    onChange,
    options,
}: {
    ariaLabel: string;
    value: string;
    onChange: (value: string) => void;
    options: Array<{ value: string; label: string }>;
}) {
    return (
        <Select value={value} onValueChange={onChange}>
            <SelectTrigger
                aria-label={ariaLabel}
                className="min-w-[160px] rounded-[11px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm outline-none transition focus-visible:border-[#0144a0] focus-visible:ring-4 focus-visible:ring-[#0144a0]/10 data-[placeholder]:text-slate-500"
            >
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                <SelectGroup>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    );
}

const CourseRow = memo(function CourseRow({
    item,
    transientAccessLink,
    onCopy,
    onRegenerate,
    isRegenerating,
    onEdit,
    onArchive,
}: {
    item: AdminCourseListItem;
    transientAccessLink?: string;
    onCopy: (item: AdminCourseListItem) => void | Promise<void>;
    onRegenerate: (item: AdminCourseListItem) => void | Promise<void>;
    isRegenerating: boolean;
    onEdit: (item: AdminCourseListItem) => void;
    onArchive: (item: AdminCourseListItem) => void;
}) {
    const courseStatus = useMemo(() => getCourseStatusMeta(item.status), [item.status]);
    const teacherState = useMemo(() => getTeacherStateMeta(item.teacher_state), [item.teacher_state]);
    const capacityColor = useMemo(() => getCapacityColor(item.occupancy_percent), [item.occupancy_percent]);
    const linkState = useMemo(
        () => buildLinkPresentation(item, transientAccessLink ? { [item.id]: transientAccessLink } : {}),
        [item, transientAccessLink],
    );
    const showRegenerateAction = !linkState.rawLink && linkState.canRegenerate && item.access_link_status === "active";

    return (
        <tr className="group transition-colors hover:bg-slate-50/80">
            <td className="px-5 py-3.5 align-middle">
                <ActionsCell
                    item={item}
                    onEdit={() => onEdit(item)}
                    onArchive={() => onArchive(item)}
                    onRegenerate={showRegenerateAction ? (() => onRegenerate(item)) : null}
                    isRegenerating={isRegenerating}
                />
            </td>
            <td className="px-5 py-3.5 align-middle"><CourseCell item={item} /></td>
            <td className="px-5 py-3.5 align-middle"><TeacherCell item={item} teacherState={teacherState} /></td>
            <td className="px-5 py-3.5 align-middle"><StatusCell courseStatus={courseStatus} /></td>
            <td className="min-w-[130px] px-5 py-3.5 align-middle"><CapacityCell item={item} capacityColor={capacityColor} /></td>
            <td className="px-5 py-3.5 align-middle max-w-[220px]">
                <LinkCell
                    item={item}
                    linkState={linkState}
                    onCopy={() => void onCopy(item)}
                />
            </td>
        </tr>
    );
});

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
    const [copied, setCopied] = useState(false);

    const handleCopy = () => {
        if (!linkState.rawLink) return;
        onCopy();
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50 transition-colors focus-within:border-slate-300 focus-within:ring-1 focus-within:ring-slate-300">
                {/* Texto a la izquierda */}
                <span
                    className="min-w-0 flex-1 truncate px-3 py-2 font-mono text-[12px] text-slate-500"
                    title={linkState.text}
                >
                    {linkState.text}
                </span>

                {/* Botón a la derecha con estado de copiado */}
                <button
                    type="button"
                    onClick={handleCopy}
                    disabled={!linkState.rawLink}
                    aria-label={`Copiar enlace de ${item.title}`}
                    title={copied ? "¡Copiado!" : "Copiar enlace"}
                    className={`flex shrink-0 items-center justify-center border-l px-2.5 py-2 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                                    copied
                                        ? "border-emerald-200 bg-emerald-50 text-emerald-600"
                                        : "border-slate-200 bg-white text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                                }`}
                >
                    {copied ? (
                        <Check className="h-4 w-4" />
                    ) : (
                        <Copy className="h-4 w-4" />
                    )}
                </button>
            </div>

            {/* Helper text */}
            <p className="text-[11px] text-slate-400">{linkState.helper}</p>
        </div>
    );
}

function ActionsCell({
    item,
    onEdit,
    onArchive,
    onRegenerate,
    isRegenerating,
}: {
    item: AdminCourseListItem;
    onEdit: () => void;
    onArchive: () => void;
    onRegenerate: (() => void) | null;
    isRegenerating: boolean;
}) {
    return (
        <div className="flex items-center justify-start gap-1 opacity-70 transition-opacity group-hover:opacity-100">
            <button type="button" onClick={onEdit} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-blue-50 hover:text-[#0144a0]" aria-label={`Editar ${item.title}`}>
                <Pencil className="h-5 w-5" />
            </button>
            {onRegenerate ? (
                <button
                    type="button"
                    onClick={onRegenerate}
                    disabled={isRegenerating}
                    className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-amber-50 hover:text-amber-600 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label={`Regenerar enlace de ${item.title}`}
                >
                    <ExternalLink className="h-5 w-5" />
                </button>
            ) : null}
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

function DashboardRefreshStatus({
    isRefreshing,
    refreshError,
    lastSyncedAt,
    onRetry,
}: {
    isRefreshing: boolean;
    refreshError: string | null;
    lastSyncedAt: number | null;
    onRetry: () => void;
}) {
    const syncLabel = useMemo(() => {
        if (!lastSyncedAt) {
            return "Cargando estado";
        }

        return `Sincronizado ${new Intl.DateTimeFormat("es-CO", {
            hour: "2-digit",
            minute: "2-digit",
        }).format(lastSyncedAt)}`;
    }, [lastSyncedAt]);

    return (
        <div className="inline-flex min-h-7 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-semibold text-slate-500" aria-live="polite" data-testid="dashboard-refresh-status">
            <span className={`h-2 w-2 rounded-full ${isRefreshing ? "animate-pulse bg-blue-500" : refreshError ? "bg-amber-500" : "bg-emerald-500"}`} />
            {isRefreshing ? (
                <span>Actualizando datos...</span>
            ) : refreshError ? (
                <>
                    <span>No se pudo actualizar. Mostrando la ultima version.</span>
                    <button type="button" onClick={onRetry} className="text-[#0144a0] transition hover:text-[#00337a]">
                        Reintentar
                    </button>
                </>
            ) : (
                <span>{syncLabel}</span>
            )}
        </div>
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
    semesterYearOptions,
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
    semesterYearOptions: string[];
    activeLinkPresentation: LinkPresentation | null;
    onCopyLink: (() => void) | null;
    onRegenerateLink: (() => void) | null;
    isRegenerating: boolean;
}) {
    const teacherFieldId = useId();
    const teacherOptionsBlocked = teacherOptionsState.isInitialLoading || (!teacherOptions && Boolean(teacherOptionsState.error));
    const modalTestId = title.toLowerCase().includes("crear") ? "create-course-modal" : "edit-course-modal";
    useEffect(() => {
        if (isOpen) {
            document.body.classList.add("overflow-hidden");
        }
        return () => {
            document.body.classList.remove("overflow-hidden");
        };
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-2xl flex flex-col max-h-[calc(100svh-3rem)] overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]" data-testid={modalTestId}>
                <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5 bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800">
                    <div>
                        <h2 className="text-xl font-bold tracking-tight text-white">{title}</h2>
                        <p className="mt-1 text-sm text-slate-300">{subtitle}</p>
                    </div>
                    <button type="button" onClick={onClose} className="rounded-lg p-1 text-white transition hover:text-slate-700" aria-label="Cerrar modal">
                        <X className="h-5 w-5" />
                    </button>
                </div>
                <form
                    onSubmit={onSubmit}
                    className="
                        space-y-5 px-6 py-6 overflow-y-auto flex-1 min-h-0
                        scrollbar-gutter-stable
                        [&::-webkit-scrollbar]:w-1.5
                        [&::-webkit-scrollbar-track]:bg-transparent
                        [&::-webkit-scrollbar-thumb]:rounded-full
                        [&::-webkit-scrollbar-thumb]:bg-blue-400
                        hover:[&::-webkit-scrollbar-thumb]:bg-indigo-400
                    "
                >
                    <div className="grid gap-5 md:grid-cols-2">
                        <Field label="Nombre del curso" value={form.title} onChange={(value) => onChange((prev) => ({ ...prev, title: value }))} placeholder="Ej. Finanzas Corporativas" />
                        <Field label="Codigo" value={form.code} onChange={(value) => onChange((prev) => ({ ...prev, code: value }))} placeholder="FIN-401" />
                        <div className="space-y-1.5 md:col-span-2">
                            <div className="grid gap-5 sm:grid-cols-2">
                                <SelectField label="Año" value={form.semester_year} onChange={(value) => onChange((prev) => ({ ...prev, semester_year: value, invalid_semester_value: null }))} options={semesterYearOptions.map((option) => ({ value: option, label: option }))} />
                                <SelectField label="Periodo" value={form.semester_term} onChange={(value) => onChange((prev) => ({ ...prev, semester_term: value as SemesterTerm, invalid_semester_value: null }))} options={SEMESTER_TERM_OPTIONS.map((option) => ({ value: option.value, label: option.label }))} />
                            </div>
                            <p className={`text-xs ${form.invalid_semester_value ? "text-red-600" : "text-slate-400"}`}>
                                {form.invalid_semester_value
                                    ? `Valor heredado invalido: ${form.invalid_semester_value}. Selecciona un año y periodo validos.`
                                    : "El semestre debe usar el formato YYYY-I o YYYY-II. Ejemplo: 2026-I."}
                            </p>
                        </div>
                        <SelectField label="Nivel academico" value={form.academic_level} onChange={(value) => onChange((prev) => ({ ...prev, academic_level: value }))} options={ACADEMIC_LEVEL_OPTIONS.map((value) => ({ value, label: value }))} />
                        <Field label="Capacidad maxima" type="number" min={1} value={form.max_students} onChange={(value) => onChange((prev) => ({ ...prev, max_students: value }))} placeholder="30" />
                        <SelectField label="Estado" value={form.status} onChange={(value) => onChange((prev) => ({ ...prev, status: value as AdminCourseStatus }))} options={COURSE_STATUS_OPTIONS} disabled={hideStatusMutation} helper={hideStatusMutation ? "El estado se cambia desde la accion Archivar para evitar restores accidentales." : undefined} />
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between gap-3">
                            <span id={`${teacherFieldId}-label`} className="text-sm font-bold text-slate-700">Docente asignado</span>
                            <button type="button" onClick={onOpenInviteTeacher} className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-[12px] font-bold text-[#0144a0] transition hover:text-[#00337a]">
                                <MailPlus className="h-3.5 w-3.5" />
                                Invitar docente
                            </button>
                        </div>
                        {teacherOptionsBlocked ? (
                            <TeacherOptionsErrorState isLoading={teacherOptionsState.isInitialLoading} error={teacherOptionsState.error} onRetry={onRetryTeacherOptions} />
                        ) : (
                            <div className="space-y-2">
                                <Select
                                    value={form.teacher_option_value === "" ? UI_UNASSIGNED_TEACHER_VALUE : form.teacher_option_value}
                                    onValueChange={(value) => onChange((prev) => ({
                                        ...prev,
                                        teacher_option_value: value === UI_UNASSIGNED_TEACHER_VALUE ? "" : value,
                                    }))}
                                >
                                    <SelectTrigger
                                        id={teacherFieldId}
                                        aria-labelledby={`${teacherFieldId}-label`}
                                        className="h-auto w-full rounded-[9px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm outline-none transition focus-visible:border-[#0144a0] focus-visible:ring-4 focus-visible:ring-[#0144a0]/10 data-[placeholder]:text-slate-500"
                                    >
                                        <SelectValue placeholder="Selecciona un docente" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value={UI_UNASSIGNED_TEACHER_VALUE}>Selecciona un docente</SelectItem>
                                        </SelectGroup>
                                        {(teacherOptions?.active_teachers.length ?? 0) > 0 && (
                                            <SelectGroup>
                                                <SelectLabel>Docentes activos</SelectLabel>
                                                {teacherOptions?.active_teachers.map((option) => (
                                                    <SelectItem key={option.membership_id} value={`membership:${option.membership_id}`}>
                                                        {option.full_name} ({option.email})
                                                    </SelectItem>
                                                ))}
                                            </SelectGroup>
                                        )}
                                        {(teacherOptions?.pending_invites.length ?? 0) > 0 && (
                                            <SelectGroup>
                                                <SelectLabel>Invitaciones pendientes</SelectLabel>
                                                {teacherOptions?.pending_invites.map((option) => (
                                                    <SelectItem key={option.invite_id} value={`pending_invite:${option.invite_id}`}>
                                                        {option.full_name} ({option.email}) - Pendiente
                                                    </SelectItem>
                                                ))}
                                            </SelectGroup>
                                        )}
                                    </SelectContent>
                                </Select>
                                <TeacherOptionsRefreshNotice
                                    isRefreshing={teacherOptionsState.isRefreshing}
                                    error={teacherOptionsState.error}
                                    onRetry={onRetryTeacherOptions}
                                />
                            </div>
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
                        <button type="button" onClick={onClose} className="inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white bg-gradient-to-br from-red-500 via-red-600 to-rose-700 shadow-[0_2px_8px_rgba(220,38,38,0.35)] transition-all duration-200 hover:from-red-600 hover:via-red-700 hover:to-rose-800 hover:shadow-[0_4px_16px_rgba(220,38,38,0.45)] hover:-translate-y-px active:translate-y-0 active:shadow-none active:scale-[0.98]"><X className="h-4 w-4" />Cancelar</button>
                        <button type="submit" disabled={isSubmitting || teacherOptionsBlocked} className="inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-bold text-white bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 shadow-[0_2px_8px_rgba(1,68,160,0.35)] transition-all duration-200 hover:from-blue-700 hover:via-blue-800 hover:to-indigo-900 hover:shadow-[0_4px_16px_rgba(1,68,160,0.45)] hover:-translate-y-px active:translate-y-0 active:shadow-none active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-[0_2px_8px_rgba(1,68,160,0.35)]">{submitLabel}</button>
                    </div>
                </form>
            </div>
        </div>
    );
}

function TeacherOptionsErrorState({
    isLoading,
    error,
    onRetry,
}: {
    isLoading: boolean;
    error: string | null;
    onRetry: () => void;
}) {
    return (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="text-sm font-semibold text-amber-900">{isLoading ? "Cargando selector de docentes..." : "No se pudo cargar el selector de docentes"}</p>
            {error && <p className="mt-1 text-sm text-amber-800">{error}</p>}
            {!isLoading && <button type="button" onClick={onRetry} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-semibold text-amber-900 transition hover:bg-amber-100">Reintentar</button>}
        </div>
    );
}

function TeacherOptionsRefreshNotice({
    isRefreshing,
    error,
    onRetry,
}: {
    isRefreshing: boolean;
    error: string | null;
    onRetry: () => void;
}) {
    if (isRefreshing) {
        return (
            <p className="text-xs font-semibold text-slate-500" aria-live="polite">
                Actualizando docentes...
            </p>
        );
    }

    if (!error) {
        return null;
    }

    return (
        <div className="flex flex-wrap items-center gap-2 text-xs text-amber-800" aria-live="polite">
            <span>No se pudieron refrescar los docentes. Sigues viendo la ultima lista disponible.</span>
            <button type="button" onClick={onRetry} className="font-semibold text-[#0144a0] transition hover:text-[#00337a]">
                Reintentar
            </button>
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
    const uiValue = value === "" ? UI_UNSET_SELECT_VALUE : value;
    return (
        <div className="block space-y-1.5">
            <span className="text-sm font-bold text-slate-700" id={`${selectId}-label`}>{label}</span>
            <Select
                value={uiValue}
                disabled={disabled}
                onValueChange={(nextValue) => onChange(nextValue === UI_UNSET_SELECT_VALUE ? "" : nextValue)}
            >
                <SelectTrigger
                    id={selectId}
                    aria-labelledby={`${selectId}-label`}
                    className="h-auto w-full rounded-[9px] border-[1.5px] border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm outline-none transition focus-visible:border-[#0144a0] focus-visible:ring-4 focus-visible:ring-[#0144a0]/10 data-[placeholder]:text-slate-500 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
                >
                    <SelectValue placeholder="Selecciona una opcion" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        {value === "" ? (
                            <SelectItem value={UI_UNSET_SELECT_VALUE}>Selecciona una opcion</SelectItem>
                        ) : null}
                        {options.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
            {helper && <p className="text-xs text-slate-400">{helper}</p>}
        </div>
    );
}

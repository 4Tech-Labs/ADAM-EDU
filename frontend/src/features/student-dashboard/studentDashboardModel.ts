import type { StudentCaseItem, StudentCaseStatus, StudentCourseItem } from "@/shared/adam-types";

type StatusTone = "blue" | "amber" | "slate";

function normalizeSearchTerm(value: string): string {
    return value
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .trim()
        .toLowerCase();
}

function parseDate(value: string | null): Date | null {
    if (!value) {
        return null;
    }

    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateTime(value: string | null): string | null {
    const parsed = parseDate(value);
    if (!parsed) {
        return null;
    }

    return new Intl.DateTimeFormat("es-CO", {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
    }).format(parsed);
}

function formatTime(value: string | null): string | null {
    const parsed = parseDate(value);
    if (!parsed) {
        return null;
    }

    return new Intl.DateTimeFormat("es-CO", {
        hour: "numeric",
        minute: "2-digit",
    }).format(parsed);
}

function isSameCalendarDay(target: Date, reference: Date): boolean {
    return target.getFullYear() === reference.getFullYear()
        && target.getMonth() === reference.getMonth()
        && target.getDate() === reference.getDate();
}

export function isPendingStudentCase(caseItem: StudentCaseItem): boolean {
    return caseItem.status !== "closed";
}

export function buildCourseCaseTitleLookup(cases: StudentCaseItem[]): Map<string, string[]> {
    const lookup = new Map<string, string[]>();
    for (const caseItem of cases) {
        for (const courseCode of caseItem.course_codes) {
            const currentTitles = lookup.get(courseCode) ?? [];
            currentTitles.push(caseItem.title);
            lookup.set(courseCode, currentTitles);
        }
    }
    return lookup;
}

export function matchesStudentCourseSearch(
    course: StudentCourseItem,
    rawSearchTerm: string,
    relatedCaseTitles: string[],
): boolean {
    if (!rawSearchTerm) {
        return true;
    }

    const searchTerm = normalizeSearchTerm(rawSearchTerm);
    const haystack = normalizeSearchTerm(
        [
            course.title,
            course.code,
            course.teacher_display_name,
            course.semester,
            course.academic_level,
            relatedCaseTitles.join(" "),
        ].join(" "),
    );
    return haystack.includes(searchTerm);
}

export function matchesStudentCaseSearch(caseItem: StudentCaseItem, rawSearchTerm: string): boolean {
    if (!rawSearchTerm) {
        return true;
    }

    const searchTerm = normalizeSearchTerm(rawSearchTerm);
    const haystack = normalizeSearchTerm(
        [caseItem.title, caseItem.course_codes.join(" ")].join(" "),
    );
    return haystack.includes(searchTerm);
}

export function formatCourseDeadlineLabel(course: StudentCourseItem): string | null {
    if (!course.next_case_title) {
        return null;
    }

    const deadline = parseDate(course.next_deadline);
    if (!deadline) {
        return `${course.next_case_title} sin fecha limite`;
    }

    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);

    if (isSameCalendarDay(deadline, now)) {
        const timeLabel = formatTime(course.next_deadline);
        return `${course.next_case_title} cierra hoy${timeLabel ? ` ${timeLabel}` : ""}`;
    }
    if (isSameCalendarDay(deadline, tomorrow)) {
        const timeLabel = formatTime(course.next_deadline);
        return `${course.next_case_title} cierra mañana${timeLabel ? ` ${timeLabel}` : ""}`;
    }

    return `${course.next_case_title} cierra ${formatDateTime(course.next_deadline)}`;
}

export function formatCaseStatusMeta(caseItem: StudentCaseItem): { label: string; tone: StatusTone } {
    if (caseItem.status === "available") {
        const deadline = parseDate(caseItem.deadline);
        if (!deadline) {
            return { label: "Disponible", tone: "blue" };
        }

        const now = new Date();
        const tomorrow = new Date(now);
        tomorrow.setDate(now.getDate() + 1);
        const timeLabel = formatTime(caseItem.deadline);

        if (isSameCalendarDay(deadline, now)) {
            return {
                label: `Vence hoy${timeLabel ? ` ${timeLabel}` : ""}`,
                tone: "amber",
            };
        }
        if (isSameCalendarDay(deadline, tomorrow)) {
            return {
                label: `Vence mañana${timeLabel ? ` ${timeLabel}` : ""}`,
                tone: "amber",
            };
        }

        return { label: `Disponible hasta el ${formatDateTime(caseItem.deadline)}`, tone: "blue" };
    }

    if (caseItem.status === "upcoming") {
        return {
            label: caseItem.available_from
                ? `Disponible ${formatDateTime(caseItem.available_from)}`
                : "Proximamente",
            tone: "amber",
        };
    }

    return {
        label: caseItem.deadline ? `Cerrado ${formatDateTime(caseItem.deadline)}` : "Cerrado",
        tone: "slate",
    };
}

export function formatCaseActionLabel(status: StudentCaseStatus): string {
    if (status === "available") {
        return "Resolver caso proximamente";
    }
    if (status === "upcoming") {
        return "Aun no disponible";
    }
    return "Feedback proximamente";
}
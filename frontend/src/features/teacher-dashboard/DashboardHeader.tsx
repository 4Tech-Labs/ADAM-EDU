import { Bell } from "lucide-react";

import { useAuth } from "@/app/auth/useAuth";

const FACULTY_SUBTITLE = "Docente · Facultad de Administración";

function getTeacherInitials(fullName: string): string {
    const parts = fullName.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "D";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase() || "D";
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export function DashboardHeader() {
    const { actor, signOut } = useAuth();
    const fullName = actor?.profile?.full_name?.trim() || "Docente";
    const initials = getTeacherInitials(fullName);

    return (
        <header
            className="w-full"
            style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)" }}
        >
            <div className="mx-auto flex h-20 max-w-6xl items-center justify-between gap-4 px-6">
                <div className="flex min-w-0 items-center gap-3.5">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/20">
                        <svg
                            className="h-6 w-6 text-white"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={2}
                            aria-hidden
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                            />
                        </svg>
                    </div>
                    <div className="min-w-0">
                        <span className="block text-lg font-bold leading-none tracking-tight text-white">
                            ADAM
                        </span>
                        <p className="mt-1 text-xs leading-none text-blue-200">
                            Diseñador de Casos
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-2 sm:gap-4">
                    <button
                        type="button"
                        aria-label="Notificaciones"
                        title="Notificaciones"
                        className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <Bell className="h-5 w-5" />
                        <span
                            aria-hidden
                            className="absolute -right-0.5 -top-0.5 h-[9px] w-[9px] rounded-full border-2 border-white bg-red-500"
                        />
                    </button>
                    <div className="h-8 w-px bg-white/20" />
                    <div className="flex min-w-0 items-center gap-3">
                        <div
                            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/20 text-[15px] font-extrabold text-white"
                            style={{ border: "2px solid rgba(255,255,255,0.35)" }}
                            aria-label={`Iniciales de ${fullName}`}
                        >
                            {initials}
                        </div>
                        <div className="hidden min-w-0 sm:block">
                            <p
                                className="truncate text-[15px] font-semibold leading-tight text-white"
                                title={fullName}
                            >
                                {fullName}
                            </p>
                            <p className="mt-0.5 text-xs leading-tight text-blue-200">
                                {FACULTY_SUBTITLE}
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={() => void signOut()}
                        aria-label="Cerrar sesión"
                        className="inline-flex h-10 shrink-0 items-center justify-center rounded-xl border border-white/20 bg-white/10 px-3 text-sm font-semibold text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <span className="sm:hidden">Salir</span>
                        <span className="hidden sm:inline">Cerrar sesión</span>
                    </button>
                </div>
            </div>
        </header>
    );
}

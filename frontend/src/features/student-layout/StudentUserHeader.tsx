import { Bell, GraduationCap } from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth/useAuth";

const STUDENT_NAME_FALLBACK = "Estudiante";
const STUDENT_SUBTITLE = "Portal Estudiante";

function getStudentInitials(fullName: string): string {
    const parts = fullName.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "ES";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase() || "ES";
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export function StudentUserHeader() {
    const { actor, signOut } = useAuth();
    const fullName = actor?.profile.full_name?.trim() || STUDENT_NAME_FALLBACK;
    const initials = getStudentInitials(fullName);

    return (
        <header
            className="w-full"
            style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)" }}
        >
            <div className="mx-auto flex h-20 max-w-6xl items-center justify-between gap-4 px-6">
                <div className="flex min-w-0 items-center gap-3.5">
                    <Link
                        to="/student/dashboard"
                        aria-label="Ir al dashboard estudiantil"
                        title="Ir al dashboard estudiantil"
                        className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25 shadow-lg shadow-black/20 backdrop-blur-sm transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-white/20 to-transparent" />
                        <GraduationCap className="relative h-[28px] w-[28px] text-white drop-shadow-sm" strokeWidth={1.75} />
                    </Link>
                    <div className="min-w-0">
                        <span className="block text-lg font-bold leading-none tracking-tight text-white">
                            ADAM
                        </span>
                        <p className="mt-1 text-xs leading-none text-blue-200">
                            Portal Académico de Casos
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
                                {STUDENT_SUBTITLE}
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
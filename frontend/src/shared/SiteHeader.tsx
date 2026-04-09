/** ADAM — Sticky site header, always visible */
import { useAuth } from "@/app/auth/useAuth";
import type { AuthMeActor } from "@/app/auth/auth-types";

const ROLE_LABEL: Record<AuthMeActor["primary_role"], string> = {
    teacher: "Portal Docente",
    student: "Portal Estudiante",
    university_admin: "Admin",
};

export function SiteHeader() {
    const { actor, signOut } = useAuth();

    const roleLabel = actor ? ROLE_LABEL[actor.primary_role] : "ADAM-EDU";

    return (
        <header
            className="sticky top-0 z-50 flex h-[58px] items-center justify-between bg-[#0144a0] px-5 shadow-md"
            data-testid="site-header"
        >
            {/* Logo */}
            <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-white">
                    <span className="font-sans text-[1.0625rem] font-bold tracking-tight text-[#0144a0]">
                        A
                    </span>
                </div>
                <span className="type-body font-semibold text-white tracking-[-0.01em]">
                    ADAM <span className="text-white/80 font-medium">Edu</span>
                </span>
            </div>

            {/* Right section */}
            <div className="flex items-center gap-4">
                {actor && (
                    <span className="type-overline text-white/80 hidden sm:inline">
                        {actor.profile.full_name}
                    </span>
                )}
                <span className="type-overline text-white/70">{roleLabel}</span>
                {actor && (
                    <button
                        onClick={() => void signOut()}
                        className="type-overline text-white/60 hover:text-white transition-colors underline underline-offset-2"
                        type="button"
                    >
                        Cerrar sesión
                    </button>
                )}
            </div>
        </header>
    );
}

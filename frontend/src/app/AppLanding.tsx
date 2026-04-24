import {
    ArrowRight,
    GraduationCap,
    ShieldCheck,
    UserRound,
    type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";

type LandingOption = {
    to: string;
    title: string;
    description: string;
    Icon: LucideIcon;
};

const LANDING_OPTIONS: LandingOption[] = [
    {
        to: "/teacher/login",
        title: "Ingresar como docente",
        description: "Gestiona cursos, casos y seguimiento",
        Icon: GraduationCap,
    },
    {
        to: "/student/login",
        title: "Ingresar como estudiante",
        description: "Accede a tus cursos, casos y notas",
        Icon: UserRound,
    },
    {
        to: "/admin/login",
        title: "Portal administrador",
        description: "Panel de control institucional",
        Icon: ShieldCheck,
    },
];

/**
 * Root landing page shown to unauthenticated users.
 * Provides real entry-point links per role — no demo toggles.
 */
export function AppLanding() {
    return (
        <div className="min-h-screen bg-[#f4f7fd] text-[#0f1f3d]">
            <div className="grid min-h-screen lg:grid-cols-[5fr_7fr]">
                <aside className="relative overflow-hidden bg-[#011e4a] px-6 py-10 sm:px-10 lg:px-[5.5rem] lg:py-14">
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0"
                        style={{
                            background:
                                "radial-gradient(ellipse 80% 60% at 20% 80%, rgba(1,85,200,0.35) 0%, transparent 60%), radial-gradient(ellipse 60% 50% at 90% 10%, rgba(1,68,160,0.5) 0%, transparent 55%)",
                        }}
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 opacity-100"
                        style={{
                            backgroundImage:
                                "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
                            backgroundSize: "48px 48px",
                        }}
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute -right-[15%] -top-[10%] aspect-square w-[70%] rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute -bottom-20 -left-20 h-80 w-80 rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute bottom-16 left-0 h-44 w-44 rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute right-[10%] top-[40%] h-24 w-24 rounded-full border border-white/10 bg-white/5"
                    />

                    <div className="relative z-10 flex h-full flex-col">
                        <div
                            className="flex items-center gap-4"
                            style={{ animation: "fadeInUp 0.5s ease both" }}
                        >
                            <div className="relative flex h-[50px] w-[50px] shrink-0 items-center justify-center rounded-[14px] border border-white/25 bg-white/10 shadow-[0_4px_16px_rgba(0,0,0,0.22),inset_0_1px_0_rgba(255,255,255,0.2),inset_0_-1px_0_rgba(0,0,0,0.1)] backdrop-blur-md">
                                <div className="absolute inset-[3px] rounded-[10px] bg-[linear-gradient(145deg,rgba(255,255,255,0.10)_0%,transparent_55%)]" />
                                <GraduationCap
                                    aria-hidden
                                    className="relative z-10 h-7 w-7 text-white"
                                    strokeWidth={2}
                                />
                            </div>
                            <div className="flex flex-col gap-1 leading-none">
                                <span className="text-[1.35rem] font-extrabold uppercase tracking-[0.12em] text-white">
                                    ADAM
                                </span>
                                <span className="text-[0.6rem] font-medium uppercase tracking-[0.15em] text-white/65">
                                    Plataforma Educativa
                                </span>
                            </div>
                        </div>

                        <div
                            className="relative z-10 mt-10 max-w-[45ch] sm:mt-12 lg:mt-[clamp(2.5rem,8vh,5rem)]"
                            style={{ animation: "fadeInUp 0.6s 0.1s ease both" }}
                        >
                            <p
                                className="mb-5 text-[clamp(2rem,2.5vw+0.5rem,3rem)] leading-[1.18] tracking-[-0.01em] text-white"
                                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                            >
                                Aprende sin
                                <br />
                                <span className="text-white/75">límites.</span>
                                <br />
                                Enseña con
                                <br />
                                impacto.
                            </p>

                            <p className="max-w-[45ch] text-base leading-[1.7] tracking-[0.01em] text-white/85 [text-shadow:0_2px_4px_rgba(0,0,0,0.2)]">
                                Casos empresariales impulsados por{" "}
                                <strong className="font-semibold text-white">
                                    IA y Data Science
                                </strong>
                                , estructurados a la medida del{" "}
                                <strong className="font-semibold text-white">
                                    currículo universitario
                                </strong>
                                . <strong className="font-semibold text-white">Optimice el tiempo</strong> de diseño académico y sumerja a los estudiantes en escenarios reales para formar{" "}
                                <span className="border-b border-white/20 font-medium text-[#69bbea]">
                                    líderes estratégicos
                                </span>
                                .
                            </p>
                        </div>
                    </div>
                </aside>

                <main className="relative flex items-center justify-center overflow-hidden bg-white px-6 py-10 sm:px-10 lg:px-14">
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0"
                        style={{
                            background:
                                "radial-gradient(ellipse 80% 50% at 100% 0%, rgba(1,68,160,0.04) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 0% 100%, rgba(1,68,160,0.03) 0%, transparent 50%)",
                        }}
                    />

                    <div className="relative z-10 w-full max-w-[400px]">
                        <header
                            className="mb-10 text-center"
                            style={{ animation: "fadeInUp 0.5s 0.15s ease both" }}
                        >
                            <h1 className="mb-2 text-[clamp(1.5rem,1.2rem+1.25vw,2.25rem)] font-bold leading-[1.15] tracking-[-0.025em] text-[#0f1f3d]">
                                Selecciona tu perfil
                            </h1>
                            <p className="mx-auto max-w-[380px] text-base font-medium leading-[1.7] text-[#6b7280]">
                                Elige el tipo de cuenta con la que deseas acceder a la plataforma.
                            </p>
                        </header>

                        <nav
                            aria-label="Selecciona tu perfil para continuar"
                            className="grid gap-4"
                        >
                            {LANDING_OPTIONS.map(({ to, title, description, Icon }, index) => (
                                <Link
                                    key={to}
                                    to={to}
                                    className="group relative flex h-[112px] w-full items-center gap-5 overflow-hidden rounded-2xl border border-transparent bg-[linear-gradient(135deg,#0144a0_0%,#0b5edd_100%)] px-6 py-5 text-left no-underline shadow-[0_6px_16px_rgba(1,68,160,0.2)] transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] hover:-translate-y-0.5 hover:bg-[linear-gradient(135deg,#012b68_0%,#0144a0_100%)] hover:shadow-[0_10px_24px_rgba(1,68,160,0.35)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#0144a0]"
                                    style={{
                                        animation: `fadeInUp 0.5s ${0.25 + index * 0.08}s ease both`,
                                    }}
                                >
                                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-white/25 bg-white/15 text-white shadow-[0_4px_12px_rgba(0,0,0,0.1)] backdrop-blur-sm transition-all duration-300 group-hover:scale-105 group-hover:bg-white/25 group-hover:shadow-[0_4px_12px_rgba(0,0,0,0.18)]">
                                        <Icon
                                            aria-hidden
                                            className="h-5 w-5"
                                            strokeWidth={2}
                                        />
                                    </div>

                                    <div className="flex min-w-0 flex-1 flex-col justify-center">
                                        <div className="text-base font-semibold leading-[1.25] tracking-[-0.01em] text-white">
                                            {title}
                                        </div>
                                        <div className="mt-1 text-sm leading-[1.4] text-white/75">
                                            {description}
                                        </div>
                                    </div>

                                    <ArrowRight
                                        aria-hidden
                                        className="h-[18px] w-[18px] shrink-0 text-white/50 transition-all duration-300 group-hover:translate-x-1 group-hover:text-white"
                                        strokeWidth={2}
                                    />
                                </Link>
                            ))}
                        </nav>

                        <footer
                            className="mt-8 text-center text-xs leading-[1.6] text-[#8b9bb8]"
                            style={{ animation: "fadeIn 0.5s 0.5s ease both" }}
                        >
                            ¿Problemas para acceder?{" "}
                            <span className="font-medium text-[#0144a0]">
                                Contacta a soporte
                            </span>
                            <br />
                            © 2026 ADAM-EDU · Todos los derechos reservados
                        </footer>
                    </div>
                </main>
            </div>
        </div>
    );
}

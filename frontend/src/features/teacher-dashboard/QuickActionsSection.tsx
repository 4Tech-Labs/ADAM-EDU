import { useNavigate } from "react-router-dom";

import type { ShowToast } from "@/shared/Toast";
import { DashboardActionCard } from "@/shared/ui/DashboardActionCard";

interface QuickActionsSectionProps {
    showToast: ShowToast;
}

function SparklesIcon() {
    return (
        <svg
            aria-hidden="true"
            className="h-5 w-5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
        >
            <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
            />
            <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
            />
        </svg>
    );
}

function ArchiveIcon() {
    return (
        <svg
            aria-hidden="true"
            className="h-5 w-5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
        >
            <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
            />
        </svg>
    );
}

function ChartIcon() {
    return (
        <svg
            aria-hidden="true"
            className="h-5 w-5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
        >
            <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
        </svg>
    );
}

export function QuickActionsSection({ showToast }: QuickActionsSectionProps) {
    const navigate = useNavigate();

    const scrollToCases = () => {
        document.getElementById("cases-section")?.scrollIntoView({ behavior: "smooth" });
    };

    return (
        <section aria-label="Acciones rápidas">
            <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                <DashboardActionCard
                    title="Crear Nuevo Caso"
                    subtitle="Genera con ADAM IA"
                    subtitleClassName="text-blue-100"
                    gradient="linear-gradient(to bottom right, #06b6d4, #3b82f6, #1d4ed8)"
                    decorativeBlurLeftClassName="bg-cyan-300/20 group-hover:bg-cyan-300/30"
                    decorativeBlurRightClassName="bg-white/10 group-hover:bg-white/20"
                    onClick={() => navigate("/teacher")}
                    icon={<SparklesIcon />}
                />
                <DashboardActionCard
                    title="Gestión de Casos"
                    subtitle="Administra y edita casos activos"
                    subtitleClassName="text-indigo-100"
                    gradient="linear-gradient(to bottom right, #8b5cf6, #6366f1, #4338ca)"
                    decorativeBlurLeftClassName="bg-violet-300/20 group-hover:bg-violet-300/30"
                    decorativeBlurRightClassName="bg-white/10 group-hover:bg-white/20"
                    onClick={scrollToCases}
                    icon={<ArchiveIcon />}
                />
                <DashboardActionCard
                    title="Reportes Globales"
                    subtitle="Próximamente en nuevas versiones"
                    subtitleClassName="text-emerald-100"
                    gradient="linear-gradient(to bottom right, #10b981, #14b8a6, #0f766e)"
                    decorativeBlurLeftClassName="bg-emerald-300/20 group-hover:bg-emerald-300/30"
                    decorativeBlurRightClassName="bg-white/10 group-hover:bg-white/20"
                    onClick={() =>
                        showToast(
                            "Reportes Globales - Próximamente en nuevas versiones...",
                            "default",
                        )
                    }
                    icon={<ChartIcon />}
                />
            </div>
        </section>
    );
}

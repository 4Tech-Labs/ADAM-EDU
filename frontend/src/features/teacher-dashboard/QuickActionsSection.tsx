import { FileText } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useToast } from "@/shared/toast-context";
import { DashboardActionCard } from "@/shared/ui/DashboardActionCard";

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
            className="h-5 w-5"
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

export function QuickActionsSection() {
    const navigate = useNavigate();
    const { showToast } = useToast();

    const scrollToCases = () => {
        document.getElementById("cases-section")?.scrollIntoView({ behavior: "smooth" });
    };

    return (
        <section aria-label="Acciones rápidas">
            <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                <DashboardActionCard
                    title="Crear Nuevo Caso"
                    subtitle="Genera con ADAM IA"
                    subtitleClassName="text-[#bcd3f0]"
                    gradient="linear-gradient(135deg, #0a5bc4 0%, #0144a0 55%, #00337a 100%)"
                    topAccentClassName="bg-gradient-to-r from-transparent via-[#8fb8f5] to-transparent"
                    leftBarClassName="bg-gradient-to-b from-white/80 to-white/30"
                    decorativeBlurLeftClassName="bg-white/10 group-hover:bg-white/20"
                    decorativeBlurRightClassName="bg-white/5 group-hover:bg-white/10"
                    onClick={() => navigate("/teacher/case-designer")}
                    icon={<FileText className="h-5 w-5 text-white" strokeWidth={1.8} />}
                />
                <DashboardActionCard
                    title="Gestión de Casos"
                    subtitle="Administra y edita casos activos"
                    subtitleClassName="text-[#bcd3f0]"
                    gradient="linear-gradient(135deg, #0a5bc4 0%, #0144a0 55%, #00337a 100%)"
                    leftBarClassName="bg-gradient-to-b from-white/80 to-white/30"
                    decorativeBlurLeftClassName="bg-white/5 group-hover:bg-white/10"
                    decorativeBlurRightClassName="bg-white/5 group-hover:bg-white/10"
                    onClick={scrollToCases}
                    icon={<ArchiveIcon />}
                />
                <button
                    type="button"
                    aria-disabled="true"
                    onClick={() =>
                        showToast(
                            "Reportes Globales - Próximamente en nuevas versiones...",
                            "info",
                        )
                    }
                    style={{ borderRadius: 16, cursor: "not-allowed" }}
                    className="flex h-[100px] items-center justify-between gap-4 border border-dashed border-[#d8d3ca] bg-[#f0ece6] p-5 text-left transition-colors hover:border-[#cfc9bf]"
                >
                    <div className="flex min-w-0 items-center gap-3">
                        <span
                            aria-hidden="true"
                            className="h-10 w-[3px] shrink-0 rounded-full bg-gradient-to-b from-[#b9bec6] to-[#d7d3ca]"
                        />
                        <div className="min-w-0">
                            <h3 className="text-[16px] font-bold tracking-tight text-[#8b93a0]">
                                Reportes Globales
                            </h3>
                            <p className="mt-1 text-xs font-medium text-[#aab1bb]">
                                Próximamente en nuevas versiones
                            </p>
                        </div>
                    </div>
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#e1dcd3] bg-[#e8e3da] text-[#a3a69f]">
                        <ChartIcon />
                    </div>
                </button>
            </div>
        </section>
    );
}

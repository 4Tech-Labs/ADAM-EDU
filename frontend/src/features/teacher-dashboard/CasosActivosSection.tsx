import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { TeacherCasesTable } from "./TeacherCasesTable";
import { useTeacherCases } from "./useTeacherDashboard";

export function CasosActivosSection() {
    const navigate = useNavigate();
    const { data, isLoading, isError } = useTeacherCases();

    return (
        <section id="cases-section" aria-labelledby="cases-heading">
            <div className="mb-6 flex items-center gap-4">
                <h2
                    id="cases-heading"
                    className="text-2xl font-bold tracking-tight text-slate-900 whitespace-nowrap"
                >
                    Casos Activos
                </h2>
                <div
                    aria-hidden="true"
                    className="ml-2 h-[2px] flex-1 rounded-full"
                    style={{
                        background: "linear-gradient(to right, #0144a0, transparent)",
                    }}
                />
                <button
                    type="button"
                    onClick={() => {
                        navigate("/teacher/case-designer");
                    }}
                    className="btn-primary inline-flex shrink-0 items-center gap-[7px] rounded-[11px] px-5 py-[10px] text-[14px] font-bold text-white"
                    style={{
                        background: "#0144a0",
                        boxShadow: "0 2px 8px rgba(1,68,160,0.25)",
                    }}
                >
                    <Plus aria-hidden="true" className="h-5 w-5" />
                    Crear nuevo caso
                </button>
            </div>

            <TeacherCasesTable
                cases={data?.cases}
                isLoading={isLoading}
                isError={isError}
                emptyMessage="No hay casos activos con deadline vigente."
                paginationNoun="casos activos"
            />
        </section>
    );
}

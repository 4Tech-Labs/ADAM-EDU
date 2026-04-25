import { useMemo } from "react";

import type { ModuleId } from "@/shared/adam-types";

import { getModuleConfig } from "./caseViewerConfig";

interface ModulesSidebarProps {
    visibleModules: ModuleId[];
    activeModule: ModuleId;
    onActiveModuleChange: (id: ModuleId) => void;
    studentProfile: string;
    caseType: string;
}

export function ModulesSidebar({
    visibleModules,
    activeModule,
    onActiveModuleChange,
    studentProfile,
    caseType,
}: ModulesSidebarProps) {
    const modules = useMemo(() => {
        const visibleSet = new Set(visibleModules);
        return getModuleConfig(studentProfile ?? "business", caseType).filter((module) => visibleSet.has(module.id));
    }, [caseType, studentProfile, visibleModules]);

    return (
        <nav className="flex-1 overflow-y-auto custom-scroll py-3">
            {modules.map((module) => {
                const isActive = activeModule === module.id;

                return (
                    <div key={module.id}>
                        {module.teacherOnly && (
                            <div className="mx-4 mt-3 mb-2">
                                <div className="border-t border-dashed" style={{ borderColor: "#7f1d1d44" }} />
                                <p className="text-[8px] font-bold uppercase tracking-widest mt-2 px-1" style={{ color: "#991b1b88" }}>
                                    Exclusivo Docente
                                </p>
                            </div>
                        )}
                        <div
                            className={`module-item${isActive ? " active" : ""}${module.teacherOnly ? " teacher-only-item" : ""}`}
                            onClick={() => onActiveModuleChange(module.id)}
                        >
                            <div
                                className="module-icon"
                                style={isActive
                                    ? {
                                        background: module.teacherOnly ? "#ef4444" : "#38bdf8",
                                        color: "#fff",
                                        borderColor: module.teacherOnly ? "#ef4444" : "#38bdf8",
                                    }
                                    : {
                                        background: "#0f172a",
                                        color: module.iconColor,
                                        borderColor: "#475569",
                                    }}
                            >
                                {module.teacherOnly ? (
                                    <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                                    </svg>
                                ) : (
                                    module.number
                                )}
                            </div>
                            <div className="min-w-0">
                                <div className="module-title">{module.name}</div>
                                <div className="module-subtitle">{module.subLabel}</div>
                            </div>
                        </div>
                    </div>
                );
            })}
        </nav>
    );
}
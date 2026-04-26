import { useCallback, useEffect, useMemo, useState } from "react";

import { useNavigate } from "react-router-dom";

import type { CanonicalCaseOutput, ModuleId } from "@/shared/adam-types";
import { usePublishCase } from "@/features/teacher-dashboard/useTeacherDashboard";
import { useToast } from "@/shared/toast-context";
import { PORTAL_SHELL_HEIGHT_VH_CLASSNAME } from "@/shared/ui/layout";
import {
    CASE_VIEWER_STYLES,
    CaseContentRenderer,
    getModuleConfig,
    ModulesSidebar,
} from "@/shared/case-viewer";

interface Props {
    caseData: CanonicalCaseOutput;
    onEditParams?: () => void;
    isPausedWaitingForApproval?: boolean;
    onResumeEDA?: () => void;
    isAlreadyPublished?: boolean;
}

export function CasePreview({
    caseData,
    onEditParams,
    isPausedWaitingForApproval,
    onResumeEDA,
    isAlreadyPublished,
}: Props) {
    const result = caseData;
    const isEDA = result.caseType === "harvard_with_eda";
    const navigate = useNavigate();

    const visibleModules = useMemo(
        () => getModuleConfig(result.studentProfile ?? "business", result.caseType),
        [result.caseType, result.studentProfile],
    );
    const visibleModuleIds = useMemo(() => visibleModules.map((module) => module.id), [visibleModules]);

    const [activeModule, setActiveModule] = useState<ModuleId>(visibleModuleIds[0] ?? "m1");
    const [isResuming, setIsResuming] = useState(false);
    const [sendState, setSendState] = useState<"idle" | "confirming" | "loading" | "sent">("idle");

    const emptyAnswers = useMemo<Record<string, string>>(() => ({}), []);
    const handleIgnoredAnswersChange = useCallback(() => undefined, []);

    const { showToast } = useToast();
    const publishCase = usePublishCase();

    useEffect(() => {
        const prev = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        return () => {
            document.body.style.overflow = prev;
        };
    }, []);

    useEffect(() => {
        if (visibleModuleIds.length > 0 && !visibleModuleIds.includes(activeModule)) {
            setActiveModule(visibleModuleIds[0]);
        }
    }, [activeModule, visibleModuleIds]);

    const handleSendClick = useCallback(() => {
        setSendState("confirming");
    }, []);

    const handleConfirmSend = useCallback(() => {
        if (!caseData.caseId) {
            return;
        }

        setSendState("loading");
        publishCase.mutate(caseData.caseId, {
            onSuccess: () => {
                setSendState("sent");
                showToast("Caso enviado exitosamente", "success");
            },
            onError: () => {
                setSendState("idle");
                showToast("Error al enviar el caso. Inténtalo de nuevo.", "error");
            },
        });
    }, [caseData.caseId, publishCase, showToast]);

    const handleDownloadHTML = useCallback(() => {
        const moduleLabel = visibleModules.find((module) => module.id === activeModule)?.name ?? activeModule;
        const panel = document.getElementById("module-content-panel");
        const htmlContent = panel?.innerHTML ?? "";
        const fullHtml = `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>${result.title} — ${moduleLabel}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..800;1,14..32,300..800&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 40px; color: #1e293b; font-size: 0.9375rem; line-height: 1.75; -webkit-font-smoothing: antialiased; }
    .prose-case { font-family: 'Inter', system-ui, sans-serif; }
    h1 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.625rem; font-weight: 700; color: #0f172a; letter-spacing: -0.02em; line-height: 1.2; }
    h2 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.0625rem; font-weight: 700; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.4rem; margin-top: 2rem; text-transform: uppercase; letter-spacing: 0.06em; }
    p { margin-bottom: 1em; font-size: 0.9375rem; line-height: 1.85; text-align: justify; hyphens: auto; }
    table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.8125rem; }
    th { background: #0f172a; color: #fff; text-transform: uppercase; font-size: 0.6875rem; letter-spacing: 0.08em; font-weight: 700; padding: 10px 16px; text-align: left; }
    td { padding: 9px 16px; border-bottom: 1px solid #f1f5f9; font-size: 0.875rem; }
    blockquote { border-left: 3px solid #cbd5e1; padding: 14px 20px; margin: 1.5rem 0; font-style: italic; background: #f8fafc; }
    ul { list-style: disc; padding-left: 1.5rem; } ol { list-style: decimal; padding-left: 1.5rem; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.8125rem; font-family: 'ui-monospace', monospace; }
    hr { border: none; height: 1.5px; background: linear-gradient(to right, #cbd5e1, transparent); margin: 2rem 0; }
  </style>
</head>
<body>
  <p style="font-size:0.6rem;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:2rem;">ADAM Academic Publishing · ${result.title}</p>
  ${htmlContent}
</body>
</html>`;

        const blob = new Blob([fullHtml], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");

        anchor.href = url;
        anchor.download = `${result.title.replace(/[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ]/g, "").replace(/\s+/g, "_")}_${activeModule}.html`;

        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    }, [activeModule, result.title, visibleModules]);

    const handleResumeClick = useCallback(() => {
        setIsResuming(true);
        onResumeEDA?.();
    }, [onResumeEDA]);

    const handleGoToTeacherDashboard = useCallback(() => {
        navigate("/teacher/dashboard", { replace: true });
    }, [navigate]);

    const showEditParamsButton = Boolean(onEditParams) && sendState !== "sent";
    const showBackToDashboardButton = sendState === "sent";

    return (
        <>
            <style>{CASE_VIEWER_STYLES}</style>
            <div className={`case-preview flex ${PORTAL_SHELL_HEIGHT_VH_CLASSNAME} overflow-hidden font-sans`}>
                <aside className="flex flex-col flex-shrink-0 bg-[#0f172a] text-slate-400" style={{ width: 280 }}>
                    <div className="h-16 flex items-center px-5 border-b border-slate-800 flex-shrink-0">
                        {showBackToDashboardButton ? (
                            <button
                                type="button"
                                onClick={handleGoToTeacherDashboard}
                                className="w-full flex items-center justify-center gap-2 bg-slate-800/80 hover:bg-[#0144a0] border border-slate-700 hover:border-[#0144a0] text-slate-300 hover:text-white py-2 px-4 rounded-lg text-sm font-semibold transition-all"
                            >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6l-6 6m0 0l6 6m-6-6h16" />
                                </svg>
                                Volver a Inicio
                            </button>
                        ) : showEditParamsButton ? (
                            <button
                                type="button"
                                onClick={onEditParams}
                                className="w-full flex items-center justify-center gap-2 bg-slate-800/80 hover:bg-[#0144a0] border border-slate-700 hover:border-[#0144a0] text-slate-300 hover:text-white py-2 px-4 rounded-lg text-sm font-semibold transition-all"
                            >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 15l-3-3m0 0l3-3m-3 3h8M3 12a9 9 0 1118 0 9 9 0 01-18 0z" />
                                </svg>
                                Volver y rehacer
                            </button>
                        ) : (
                            <div className="flex items-center gap-2.5 text-white">
                                <div className="h-8 w-8 rounded-lg bg-[#0144a0] flex items-center justify-center">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                                    </svg>
                                </div>
                                <div>
                                    <span className="font-bold tracking-tight text-base">ADAM</span>
                                    <p className="text-[10px] text-slate-500 leading-none mt-0.5">Vista Profesor</p>
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="px-5 py-3 border-b border-slate-800 flex-shrink-0">
                        <p className="text-[10px] uppercase tracking-wider text-slate-600 font-bold">Caso activo</p>
                        <p className="text-xs text-slate-300 font-medium mt-0.5 line-clamp-2">{result.title}</p>
                    </div>

                    <ModulesSidebar
                        visibleModules={visibleModuleIds}
                        activeModule={activeModule}
                        onActiveModuleChange={setActiveModule}
                        studentProfile={result.studentProfile ?? "business"}
                        caseType={result.caseType}
                    />

                    <div className="px-5 py-3 border-t border-slate-800 flex-shrink-0">
                        <div className="flex items-center gap-2 text-[10px] text-slate-600">
                            <div className={`w-2 h-2 rounded-full ${isEDA ? "bg-emerald-500" : "bg-blue-500"}`} />
                            <span>{isEDA ? "Harvard + EDA" : "Harvard Only"}</span>
                        </div>
                    </div>
                </aside>

                <main className="flex-1 flex flex-col bg-[#F0F4F8] min-w-0 overflow-hidden">
                    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 flex-shrink-0 gap-4">
                        <div className="flex items-center gap-3 min-w-0">
                            <h1 className="text-sm font-bold text-slate-800 truncate">{result.title}</h1>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                            {isPausedWaitingForApproval && !isResuming && (
                                <button
                                    type="button"
                                    onClick={handleResumeClick}
                                    className="flex items-center gap-2 px-4 py-2 bg-[#0144a0] hover:bg-[#00337a] text-white text-xs font-semibold rounded-lg transition-colors shadow-sm"
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                    Continuar con EDA
                                </button>
                            )}
                            {isResuming && (
                                <span className="flex items-center gap-2 text-xs text-violet-600 font-semibold">
                                    <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                    </svg>
                                    Generando EDA...
                                </span>
                            )}

                            <button
                                type="button"
                                onClick={handleDownloadHTML}
                                className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
                            >
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                </svg>
                                Descargar HTML
                            </button>

                            <button
                                type="button"
                                disabled
                                title="Exportación PDF próximamente"
                                className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 border border-slate-200 text-slate-400 text-xs font-semibold rounded-lg cursor-not-allowed opacity-50"
                            >
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                                </svg>
                                PDF
                            </button>

                            {!isAlreadyPublished && (
                                sendState === "sent" ? (
                                    <span className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-emerald-700">
                                        ✓ Caso enviado
                                    </span>
                                ) : sendState === "confirming" ? (
                                    <span className="flex items-center gap-2">
                                        <span className="text-xs font-semibold text-slate-700">¿Confirmar envío?</span>
                                        <button
                                            type="button"
                                            onClick={() => setSendState("idle")}
                                            className="px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
                                        >
                                            Cancelar
                                        </button>
                                        <button
                                            type="button"
                                            onClick={handleConfirmSend}
                                            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#0144a0] hover:bg-[#00337a] text-white text-xs font-semibold rounded-lg transition-colors"
                                        >
                                            Sí, enviar
                                        </button>
                                    </span>
                                ) : (
                                    <button
                                        type="button"
                                        aria-label="Enviar caso al estudiante"
                                        disabled={!caseData.caseId || sendState === "loading"}
                                        onClick={handleSendClick}
                                        className="flex items-center gap-1.5 px-3 py-2 bg-[#0144a0] hover:bg-[#00337a] hover:shadow-md active:scale-95 text-white text-xs font-semibold rounded-lg transition-all duration-150 ease-out disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none"
                                    >
                                        {sendState === "loading" ? (
                                            <>
                                                <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                                </svg>
                                                Enviando...
                                            </>
                                        ) : (
                                            <>
                                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                                                </svg>
                                                Enviar Caso
                                            </>
                                        )}
                                    </button>
                                )
                            )}
                        </div>
                    </header>

                    <CaseContentRenderer
                        result={result}
                        visibleModules={visibleModuleIds}
                        activeModule={activeModule}
                        onActiveModuleChange={setActiveModule}
                        answers={emptyAnswers}
                        onAnswersChange={handleIgnoredAnswersChange}
                        readOnly={true}
                        showExpectedSolutions={true}
                    />
                </main>
            </div>
        </>
    );
}

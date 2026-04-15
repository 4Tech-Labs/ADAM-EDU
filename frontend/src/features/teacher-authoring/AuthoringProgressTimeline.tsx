/** AuthoringProgressTimeline: muestra progreso del pipeline */

import { useEffect, useState, useRef } from "react";
import type { AuthoringProgressStep } from "@/shared/adam-types";

interface Props {
  activeAgent?: AuthoringProgressStep;
  scope: "narrative" | "technical";
  jobStatus?: "pending" | "processing" | "completed" | "failed" | "failed_resumable";
}

const PIPELINE_STEPS: Array<{
  id: AuthoringProgressStep;
  label: string;
  detail: string;
  scope: "both" | "technical";
}> = [
  {
    id: "case_architect",
    label: "Diseñando arquitectura del caso",
    detail: "Estructura, dilema y datos numéricos (M1)",
    scope: "both",
  },
  {
    id: "case_writer",
    label: "Redactando narrativa",
    detail: "Historia del caso y preguntas M1",
    scope: "both",
  },
  {
    id: "eda_text_analyst",
    label: "Analizando datos (EDA)",
    detail: "Reporte exploratorio y visualizaciones M2",
    scope: "technical",
  },
  {
    id: "m3_content_generator",
    label: "Auditando evidencia",
    detail: "Validación crítica de los datos M2 (M3)",
    scope: "technical",
  },
  {
    id: "m4_content_generator",
    label: "Calculando impacto financiero",
    detail: "Proyección de valor y gráficos M4",
    scope: "both",
  },
  {
    id: "m5_content_generator",
    label: "Elaborando recomendación ejecutiva",
    detail: "Síntesis y reporte BLUF (M5)",
    scope: "both",
  },
  {
    id: "teaching_note_part1",
    label: "Generando material del docente",
    detail: "Teaching Note e Informe de Resolución (M6)",
    scope: "both",
  },
];

type StepStatus = "pending" | "active" | "done";

function getStepStatus(
  stepIndex: number,
  effectiveIndex: number,
  jobStatus?: string
): StepStatus {
  if (jobStatus === "completed") return "done";
  if (effectiveIndex >= 0) {
    if (stepIndex < effectiveIndex) return "done";
    if (stepIndex === effectiveIndex) return "active";
    return "pending";
  }
  // Fallback: cuando estamos procesando pero aún sin step canónico conocido
  if (jobStatus === "processing") {
    return stepIndex === 0 ? "active" : "pending";
  }
  return "pending";
}

export function AuthoringProgressTimeline({ activeAgent, scope, jobStatus }: Props) {
  const [dots, setDots] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const lastValidIndexRef = useRef<number>(-1);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "" : d + "."));
    }, 500);
    return () => clearInterval(interval);
  }, []);

  const visibleSteps = scope === "narrative"
    ? PIPELINE_STEPS.filter((s) => s.scope !== "technical")
    : PIPELINE_STEPS;

  const activeIndex = visibleSteps.findIndex((s) => s.id === activeAgent);
  // Sticky index: si el activeAgent no coincide con ningún paso (subnodo paralelo),
  // nos quedamos en el último paso conocido en lugar de resetear el progreso a 0.
  if (activeIndex >= 0) lastValidIndexRef.current = activeIndex;
  const effectiveIndex = activeIndex >= 0 ? activeIndex : lastValidIndexRef.current;

  const inferredActiveIndex = effectiveIndex >= 0
    ? effectiveIndex
    : (jobStatus === "processing" ? 0 : -1);
  const currentProgressIndex = jobStatus === "completed"
    ? visibleSteps.length
    : (inferredActiveIndex >= 0 ? inferredActiveIndex + 1 : 0);
  const safeCurrentProgressIndex = Math.max(0, Math.min(currentProgressIndex, visibleSteps.length));
  const progressPercent = Math.round((safeCurrentProgressIndex / visibleSteps.length) * 100);

  useEffect(() => {
    if (scrollContainerRef.current) {
      const activeElement = scrollContainerRef.current.querySelector('[data-active="true"]');
      if (activeElement) {
        activeElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }, [effectiveIndex]);

  return (
    // Redujimos el padding global de p-10 a p-4/p-6
    <div className="flex w-full items-center justify-center min-h-[calc(100vh-64px)] p-4 md:p-6 bg-[#f6f5f0]">

      {/* Tarjeta: max-w de 5xl a 4xl, altura máxima reducida de 600px a 480px */}
      <div className="w-full max-w-4xl bg-white rounded-2xl shadow-[0_15px_40px_-12px_rgba(0,0,0,0.06)] border border-slate-100 flex flex-col md:flex-row overflow-hidden max-h-[85vh] md:max-h-[480px]">

        {/* Panel Izquierdo: Paddings reducidos (de p-12 a p-8) */}
        <div className="flex flex-col md:w-2/5 p-6 md:p-8 md:pr-6 bg-white z-10 justify-between">

          <div className="flex flex-col items-center md:items-start">
            {/* Círculo radial reducido de w-28 a w-20 */}
            <div className="relative flex items-center justify-center w-20 h-20 mb-6 mx-auto md:mx-0">
              <svg className="absolute inset-0 w-full h-full text-slate-100" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeWidth="6" />
              </svg>
              <svg
                className="absolute inset-0 w-full h-full text-[#0144a0] drop-shadow-sm transition-all duration-1000 ease-out"
                viewBox="0 0 100 100"
                style={{ transform: "rotate(-90deg)" }}
              >
                <circle
                  cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeWidth="6" strokeDasharray="289"
                  strokeDashoffset={289 - (289 * progressPercent) / 100} strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/40 rounded-full backdrop-blur-[1px]">
                <span className="text-2xl font-black text-[#0144a0] tracking-tighter">{progressPercent}%</span>
              </div>
            </div>

            <div className="space-y-2 w-full">
              {/* Textos escalados de 3xl a 2xl, y base a sm */}
              <h2 className="text-2xl font-extrabold text-slate-800 tracking-tight leading-tight flex items-end justify-center md:justify-start">
                Generando caso
                <span className="inline-block w-4 text-left text-[#0144a0] animate-pulse">{dots}</span>
              </h2>
              <p className="text-sm text-slate-500 leading-relaxed max-w-[240px] mx-auto md:mx-0 text-center md:text-left">
                Los agentes de ADAM están analizando y construyendo tu caso de forma orquestada.
              </p>
            </div>
          </div>

          <div className="hidden md:flex flex-col gap-2 mt-8 w-full">
            <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase tracking-widest">
              <span>Progreso del pipeline</span>
              <span>{safeCurrentProgressIndex}/{visibleSteps.length}</span>
            </div>
            <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-[#0144a0] to-blue-400 rounded-full transition-all duration-1000 relative"
                style={{ width: `${progressPercent}%` }}
              >
                <div className="absolute top-0 left-0 w-full h-full bg-white/20 animate-pulse"></div>
              </div>
            </div>
          </div>
        </div>

        {/* Panel Derecho */}
        <div className="flex-1 w-full relative h-full flex flex-col bg-white border-l border-slate-50">

          <div className="absolute top-0 left-0 right-0 h-6 bg-gradient-to-b from-white to-transparent z-10 pointer-events-none"></div>
          <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-white to-transparent z-10 pointer-events-none"></div>

          {/* Padding interno del scroll reducido */}
          <div
            ref={scrollContainerRef}
            className="flex-1 overflow-y-auto pl-5 pr-6 md:pr-8 py-6 pb-16 space-y-0 scrollbar-thin scrollbar-thumb-slate-200 scrollbar-track-transparent"
          >
            {visibleSteps.map((step, i) => {
              const status = getStepStatus(i, effectiveIndex, jobStatus);
              const isLast = i === visibleSteps.length - 1;
              const isActive = status === "active";

              return (
                <div
                  key={step.id}
                  data-active={isActive}
                  className="relative flex items-stretch group"
                >
                  <div className="flex flex-col items-center mr-4">
                    {/* Íconos reducidos de h-8 w-8 a h-6 w-6 */}
                    <div className="relative z-10 flex-shrink-0 flex items-center justify-center h-6 w-6">
                      {status === "done" ? (
                        <div className="h-6 w-6 rounded-full bg-emerald-500 shadow-sm flex items-center justify-center transform transition-transform group-hover:scale-105">
                          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        </div>
                      ) : isActive ? (
                        <div className="relative flex items-center justify-center h-6 w-6">
                          <div className="absolute inset-0 rounded-full bg-blue-100 animate-ping opacity-70"></div>
                          <div className="relative h-6 w-6 rounded-full border-[2.5px] border-[#0144a0] border-t-transparent animate-spin"></div>
                          <div className="absolute h-1.5 w-1.5 bg-[#0144a0] rounded-full"></div>
                        </div>
                      ) : (
                        <div className="h-6 w-6 rounded-full border-[1.5px] border-slate-200 bg-white transition-colors group-hover:border-slate-300" />
                      )}
                    </div>

                    {!isLast && (
                      <div className={`w-[2px] flex-grow my-1 rounded-full transition-colors duration-500 min-h-[28px] ${status === "done" ? "bg-emerald-400" : "bg-slate-100"
                        }`} />
                    )}
                  </div>

                  {/* Paddings entre pasos (pb-5) y textos escalados un 15% más pequeños */}
                  <div className={`flex-1 pb-5 transition-all duration-300 flex flex-col justify-start pt-0.5 ${isActive ? "opacity-100 translate-x-1" :
                    status === "done" ? "opacity-90" : "opacity-40"
                    }`}>
                    <div className="flex flex-row items-center justify-between gap-2">
                      <p className={`text-[15px] font-bold leading-tight ${isActive ? "text-[#0144a0]" :
                        status === "done" ? "text-slate-800" : "text-slate-500"
                        }`}>
                        {step.label}
                      </p>
                      {isActive && (
                        <span className="flex-shrink-0 text-[9px] uppercase tracking-widest font-bold text-[#0144a0] bg-blue-50 border border-blue-100 px-2 py-0.5 rounded shadow-sm">
                          En proceso
                        </span>
                      )}
                    </div>
                    <p className={`text-[12px] mt-1 leading-snug ${isActive ? "text-slate-600 font-medium" : "text-slate-400"
                      }`}>
                      {step.detail}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

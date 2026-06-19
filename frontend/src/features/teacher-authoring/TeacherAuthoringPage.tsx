/** ADAM v8 - Portal Profesor: Builder Mode (Supabase Realtime Flow) */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import type { CaseFormData, CanonicalCaseOutput } from "@/shared/adam-types";
import { EMPTY_FORM } from "@/shared/adam-types";
import { api } from "@/shared/api";
import { useToast } from "@/shared/toast-context";
import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";

import { AuthoringErrorState } from "./AuthoringErrorState";
import { AuthoringForm } from "./AuthoringForm";
import { AuthoringProgressTimeline } from "./AuthoringProgressTimeline";
import { useAuthoringJobProgress } from "./useAuthoringJobProgress";
import { FORM_STATE_SESSION_KEY } from "./authoringFormConfig";

type AppState = "idle" | "generating" | "editing" | "error" | "success" | "paused";

const CasePreview = lazy(() =>
  import("@/features/case-preview/CasePreview").then((module) => ({
    default: module.CasePreview,
  })),
);

const LiveCasePreview = lazy(() =>
  import("@/features/case-preview/LiveCasePreview").then((module) => ({
    default: module.LiveCasePreview,
  })),
);

function CasePreviewFallback() {
  return (
    <div className="flex items-center justify-center py-24">
      <span className="text-sm text-muted-foreground">
        Cargando vista previa...
      </span>
    </div>
  );
}

export function TeacherAuthoringPage() {
  const [appState, setAppState] = useState<AppState>("idle");
  const [formData, setFormData] = useState<CaseFormData>(EMPTY_FORM);
  const [caseResult, setCaseResult] = useState<CanonicalCaseOutput | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const retryInFlightRef = useRef(false);

  const { showToast } = useToast();
  const [isRegeneratingNotebook, setIsRegeneratingNotebook] = useState(false);

  const {
    jobId,
    status: jobStatus,
    errorTrace,
    result: jobResult,
    activeAgent,
    submitJob,
    retryJob,
    reset: resetJob,
    isStreaming,
    progressScope,
    bootstrapState,
  } = useAuthoringJobProgress();

  useEffect(() => {
    if (isStreaming || jobStatus === "pending" || jobStatus === "processing") {
      setAppState("generating");
      setErrorMessage("");
    } else if (jobStatus === "failed" || jobStatus === "failed_resumable") {
      setAppState("error");
      if (errorTrace && errorTrace.trim() !== "") {
        setErrorMessage(errorTrace);
      } else if (jobStatus === "failed_resumable") {
        setErrorMessage("La generacion se interrumpio por un error transitorio. Puedes reintentar sin perder el progreso ya completado.");
      } else {
        setErrorMessage("Error desconocido durante la generacion.");
      }
    } else if (jobStatus === "completed" && jobResult) {
      setCaseResult(jobResult);
      setAppState("success");
    }
  }, [isStreaming, jobStatus, errorTrace, jobResult]);

  const handleGenerate = useCallback(
    async (data: CaseFormData) => {
      setFormData(data);
      setErrorMessage("");
      await submitJob(data);
    },
    [submitJob],
  );

  // ── Clear form sessionStorage when the job completes successfully ──
  useEffect(() => {
    if (appState === "success") {
      sessionStorage.removeItem(FORM_STATE_SESSION_KEY);
    }
  }, [appState]);

  const handleResumeEDA = useCallback(() => {
    // Placeholder para un futuro flujo HITL.
  }, []);

  const handleRegenerateNotebook = useCallback(async () => {
    if (!jobId || isRegeneratingNotebook) {
      return;
    }
    setIsRegeneratingNotebook(true);
    try {
      await api.authoring.regenerateNotebook(jobId);
      // The regeneration runs in the background and patches the canonical output.
      // Poll the result until the notebook is no longer degraded (bounded).
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        const res = await api.authoring.getResult(jobId);
        const updated = res.canonical_output as CanonicalCaseOutput | undefined;
        if (updated && !updated.content?.m3NotebookDegraded) {
          setCaseResult(updated);
          showToast("Notebook regenerado correctamente.", "success");
          return;
        }
      }
      showToast("La regeneración está tardando más de lo previsto. Intenta de nuevo en un momento.", "error");
    } catch {
      showToast("No se pudo regenerar el notebook. Intenta de nuevo.", "error");
    } finally {
      setIsRegeneratingNotebook(false);
    }
  }, [jobId, isRegeneratingNotebook, showToast]);

  const handleRetry = useCallback(async () => {
    if (jobStatus === "failed_resumable") {
      if (retryInFlightRef.current) {
        return;
      }

      retryInFlightRef.current = true;
      setErrorMessage("");
      try {
        setAppState("generating");
        await retryJob();
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : "Error al reintentar.");
        setAppState("error");
      } finally {
        retryInFlightRef.current = false;
      }
      return;
    }

    resetJob();
    setAppState("idle");
  }, [jobStatus, resetJob, retryJob]);

  const isPreviewActive = appState === "success" || appState === "paused";

  return (
    <TeacherLayout
      testId="teacher-authoring-page"
      contentClassName={isPreviewActive ? "w-full p-0" : "mx-auto w-full max-w-6xl"}
    >
      {(appState === "idle" || appState === "editing") && (
        <AuthoringForm
          initialData={formData}
          onSubmit={handleGenerate}
          showCancelEdit={appState === "editing"}
          onCancelEdit={() => setAppState("success")}
        />
      )}

      {appState === "generating" && (
        <div className="flex flex-col gap-6">
          <AuthoringProgressTimeline
            activeAgent={activeAgent}
            bootstrapState={bootstrapState}
            jobStatus={jobStatus || undefined}
            scope={progressScope || (formData.caseType === "harvard_only" ? "narrative" : "technical")}
          />
          {jobResult && (
            <Suspense fallback={<CasePreviewFallback />}>
              <LiveCasePreview caseData={jobResult} isStreaming={true} />
            </Suspense>
          )}
        </div>
      )}

      {(appState === "success" || appState === "paused") && caseResult && (
        <Suspense fallback={<CasePreviewFallback />}>
          <CasePreview
            caseData={caseResult}
            onEditParams={() => setAppState("editing")}
            isPausedWaitingForApproval={appState === "paused"}
            onResumeEDA={handleResumeEDA}
            onRegenerateNotebook={handleRegenerateNotebook}
            isRegeneratingNotebook={isRegeneratingNotebook}
          />
        </Suspense>
      )}

      {appState === "error" && (
        <div className="flex flex-col gap-6">
          <AuthoringErrorState
            message={errorMessage}
            onRetry={jobStatus === "failed_resumable" ? handleRetry : undefined}
            onBack={() => setAppState("idle")}
          />
          {jobResult && (
            <>
              <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                <strong className="font-semibold">Borrador no guardado.</strong>{" "}
                La generación se interrumpió; los módulos de abajo son un borrador parcial y no se guardaron.
              </div>
              <Suspense fallback={<CasePreviewFallback />}>
                <LiveCasePreview caseData={jobResult} isStreaming={false} />
              </Suspense>
            </>
          )}
        </div>
      )}
    </TeacherLayout>
  );
}

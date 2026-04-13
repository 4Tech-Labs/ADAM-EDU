/** ADAM v8 - Portal Profesor: Builder Mode (Native SSE Flow) */

import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import type { CaseFormData, CanonicalCaseOutput } from "@/shared/adam-types";
import { EMPTY_FORM } from "@/shared/adam-types";
import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";

import { AuthoringErrorState } from "./AuthoringErrorState";
import { AuthoringForm } from "./AuthoringForm";
import { AuthoringProgressTimeline } from "./AuthoringProgressTimeline";
import { useAuthoringJobProgress } from "./useAuthoringJobProgress";

type AppState = "idle" | "generating" | "editing" | "error" | "success" | "paused";

const CasePreview = lazy(() =>
  import("@/features/case-preview/CasePreview").then((module) => ({
    default: module.CasePreview,
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

  const {
    status: jobStatus,
    errorTrace,
    result: jobResult,
    activeAgent,
    submitJob,
    reset: resetJob,
  } = useAuthoringJobProgress();

  useEffect(() => {
    if (jobStatus === "pending" || jobStatus === "processing") {
      setAppState("generating");
      setErrorMessage("");
    } else if (jobStatus === "failed") {
      setAppState("error");
      setErrorMessage(errorTrace || "Error desconocido durante la generacion.");
    } else if (jobStatus === "completed" && jobResult) {
      setCaseResult(jobResult);
      setAppState("success");
    }
  }, [jobStatus, errorTrace, jobResult]);

  const handleGenerate = useCallback(
    async (data: CaseFormData) => {
      setFormData(data);
      setErrorMessage("");
      await submitJob(data);
    },
    [submitJob],
  );

  const handleResumeEDA = useCallback(() => {
    // Placeholder para un futuro flujo HITL.
  }, []);

  const handleRetry = () => {
    resetJob();
    setAppState("idle");
  };

  return (
    <TeacherLayout testId="teacher-authoring-page" contentClassName="mx-auto w-full max-w-6xl">
      {(appState === "idle" || appState === "editing") && (
        <AuthoringForm
          initialData={formData}
          onSubmit={handleGenerate}
          showCancelEdit={appState === "editing"}
          onCancelEdit={() => setAppState("success")}
        />
      )}

      {appState === "generating" && (
        <AuthoringProgressTimeline
          activeAgent={activeAgent}
          jobStatus={jobStatus || undefined}
          scope={formData.caseType === "harvard_only" ? "narrative" : "technical"}
        />
      )}

      {(appState === "success" || appState === "paused") && caseResult && (
        <Suspense fallback={<CasePreviewFallback />}>
          <CasePreview
            caseData={caseResult}
            onEditParams={() => setAppState("editing")}
            isPausedWaitingForApproval={appState === "paused"}
            onResumeEDA={handleResumeEDA}
          />
        </Suspense>
      )}

      {appState === "error" && (
        <AuthoringErrorState
          message={errorMessage}
          onRetry={handleRetry}
          onBack={() => setAppState("idle")}
        />
      )}
    </TeacherLayout>
  );
}

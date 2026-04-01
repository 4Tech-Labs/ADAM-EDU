import { Routes, Route, Navigate } from "react-router-dom";
import { SiteHeader } from "@/shared/SiteHeader";
import { useToast } from "@/shared/Toast";

import { TeacherAuthoringPage } from "@/features/teacher-authoring/TeacherAuthoringPage";

function App() {
  const { ToastContainer } = useToast();

  return (
    <div className="flex min-h-screen flex-col bg-bg-page font-sans type-body">
      <SiteHeader />

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/teacher" replace />} />
          <Route path="/teacher/*" element={<TeacherAuthoringPage />} />
        </Routes>
      </main>

      <ToastContainer />
    </div>
  );
}

export default App;

import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { SiteHeader } from "@/shared/SiteHeader";
import { useToast } from "@/shared/Toast";

import { TeacherAuthoringPage } from "@/features/teacher-authoring/TeacherAuthoringPage";
import { AuthCallbackPage } from "@/features/auth-callback/AuthCallbackPage";
import { TeacherLoginPage } from "@/features/teacher-auth/TeacherLoginPage";
import { TeacherActivatePage } from "@/features/teacher-auth/TeacherActivatePage";
import { StudentLoginPage } from "@/features/student-auth/StudentLoginPage";
import { StudentJoinPage } from "@/features/student-auth/StudentJoinPage";
import { AdminLoginPage } from "@/features/admin-auth/AdminLoginPage";
import { AdminChangePasswordPage } from "@/features/admin-auth/AdminChangePasswordPage";
import { AdminDashboardPage } from "@/features/admin-dashboard/AdminDashboardPage";

import { RootRedirect } from "./auth/RootRedirect";
import { RequireRole } from "./auth/RequireRole";
import { RequirePasswordRotation } from "./auth/RequirePasswordRotation";
import { GuestOnlyRoute } from "./auth/GuestOnlyRoute";

function App() {
    const { ToastContainer, showToast } = useToast();
    const location = useLocation();
    const isAdminDashboardRoute = location.pathname.startsWith("/admin/dashboard");

    return (
        <div className="flex min-h-screen flex-col bg-bg-page font-sans type-body">
            {!isAdminDashboardRoute && <SiteHeader />}

            <main className="flex-1">
                <Routes>
                    {/* Root — redirects by session/role or shows landing */}
                    <Route path="/" element={<RootRedirect />} />

                    {/* Teacher routes */}
                    <Route path="/teacher/login" element={<GuestOnlyRoute role="teacher"><TeacherLoginPage /></GuestOnlyRoute>} />
                    <Route path="/teacher/activate" element={<TeacherActivatePage />} />
                    <Route
                        path="/teacher/*"
                        element={
                            <RequireRole role="teacher">
                                <TeacherAuthoringPage />
                            </RequireRole>
                        }
                    />

                    {/* Student routes */}
                    <Route path="/student/login" element={<GuestOnlyRoute role="student"><StudentLoginPage /></GuestOnlyRoute>} />
                    <Route path="/join" element={<StudentJoinPage />} />
                    <Route
                        path="/student/*"
                        element={
                            <RequireRole role="student">
                                <div className="flex flex-col items-center justify-center gap-4 px-4 py-24 text-center">
                                    <h1 className="text-xl font-semibold">Panel del estudiante</h1>
                                    <p className="text-sm text-muted-foreground max-w-xs">
                                        El panel completo estará disponible en la próxima versión.
                                    </p>
                                </div>
                            </RequireRole>
                        }
                    />

                    {/* Admin routes */}
                    <Route path="/admin/login" element={<GuestOnlyRoute role="university_admin"><AdminLoginPage /></GuestOnlyRoute>} />
                    <Route
                        path="/admin/change-password"
                        element={
                            <RequirePasswordRotation>
                                <AdminChangePasswordPage />
                            </RequirePasswordRotation>
                        }
                    />
                    <Route
                        path="/admin/dashboard"
                        element={
                            <RequireRole role="university_admin">
                                <AdminDashboardPage showToast={showToast} />
                            </RequireRole>
                        }
                    />

                    {/* OAuth callback — PKCE code exchange handled by Supabase */}
                    <Route path="/auth/callback" element={<AuthCallbackPage />} />

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </main>

            <ToastContainer />
        </div>
    );
}

export default App;

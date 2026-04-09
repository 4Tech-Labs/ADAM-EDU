import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { SiteHeader } from "@/shared/SiteHeader";
import { useToast } from "@/shared/Toast";

import { GuestOnlyRoute } from "./auth/GuestOnlyRoute";
import { RequirePasswordRotation } from "./auth/RequirePasswordRotation";
import { RequireRole } from "./auth/RequireRole";
import { RootRedirect } from "./auth/RootRedirect";

const TeacherAuthoringPage = lazy(() =>
    import("@/features/teacher-authoring/TeacherAuthoringPage").then(
        (module) => ({ default: module.TeacherAuthoringPage }),
    ),
);
const AuthCallbackPage = lazy(() =>
    import("@/features/auth-callback/AuthCallbackPage").then((module) => ({
        default: module.AuthCallbackPage,
    })),
);
const TeacherLoginPage = lazy(() =>
    import("@/features/teacher-auth/TeacherLoginPage").then((module) => ({
        default: module.TeacherLoginPage,
    })),
);
const TeacherActivatePage = lazy(() =>
    import("@/features/teacher-auth/TeacherActivatePage").then((module) => ({
        default: module.TeacherActivatePage,
    })),
);
const StudentLoginPage = lazy(() =>
    import("@/features/student-auth/StudentLoginPage").then((module) => ({
        default: module.StudentLoginPage,
    })),
);
const StudentJoinPage = lazy(() =>
    import("@/features/student-auth/StudentJoinPage").then((module) => ({
        default: module.StudentJoinPage,
    })),
);
const AdminLoginPage = lazy(() =>
    import("@/features/admin-auth/AdminLoginPage").then((module) => ({
        default: module.AdminLoginPage,
    })),
);
const AdminChangePasswordPage = lazy(() =>
    import("@/features/admin-auth/AdminChangePasswordPage").then((module) => ({
        default: module.AdminChangePasswordPage,
    })),
);
const AdminDashboardPage = lazy(() =>
    import("@/features/admin-dashboard/AdminDashboardPage").then((module) => ({
        default: module.AdminDashboardPage,
    })),
);

function RouteFallback() {
    return (
        <div className="flex items-center justify-center py-24">
            <span className="text-sm text-muted-foreground">
                Cargando pagina...
            </span>
        </div>
    );
}

function App() {
    const { ToastContainer, showToast } = useToast();
    const location = useLocation();
    const isAdminDashboardRoute = location.pathname.startsWith("/admin/dashboard");

    return (
        <div className="flex min-h-screen flex-col bg-bg-page font-sans type-body">
            {!isAdminDashboardRoute && <SiteHeader />}

            <main className="flex-1">
                <Suspense fallback={<RouteFallback />}>
                    <Routes>
                        <Route path="/" element={<RootRedirect />} />

                        <Route
                            path="/teacher/login"
                            element={
                                <GuestOnlyRoute role="teacher">
                                    <TeacherLoginPage />
                                </GuestOnlyRoute>
                            }
                        />
                        <Route path="/teacher/activate" element={<TeacherActivatePage />} />
                        <Route
                            path="/teacher/*"
                            element={
                                <RequireRole role="teacher">
                                    <TeacherAuthoringPage />
                                </RequireRole>
                            }
                        />

                        <Route
                            path="/student/login"
                            element={
                                <GuestOnlyRoute role="student">
                                    <StudentLoginPage />
                                </GuestOnlyRoute>
                            }
                        />
                        <Route path="/join" element={<StudentJoinPage />} />
                        <Route
                            path="/student/*"
                            element={
                                <RequireRole role="student">
                                    <div className="flex flex-col items-center justify-center gap-4 px-4 py-24 text-center">
                                        <h1 className="text-xl font-semibold">Panel del estudiante</h1>
                                        <p className="max-w-xs text-sm text-muted-foreground">
                                            El panel completo estara disponible en la proxima version.
                                        </p>
                                    </div>
                                </RequireRole>
                            }
                        />

                        <Route
                            path="/admin/login"
                            element={
                                <GuestOnlyRoute role="university_admin">
                                    <AdminLoginPage />
                                </GuestOnlyRoute>
                            }
                        />
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

                        <Route path="/auth/callback" element={<AuthCallbackPage />} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                </Suspense>
            </main>

            <ToastContainer />
        </div>
    );
}

export default App;

import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { SiteHeader } from "@/shared/SiteHeader";
import { ToastProvider } from "@/shared/Toast";

import { GuestOnlyRoute } from "./auth/GuestOnlyRoute";
import { RequirePasswordRotation } from "./auth/RequirePasswordRotation";
import { RequireRole } from "./auth/RequireRole";
import { RootRedirect } from "./auth/RootRedirect";

const TeacherAuthoringPage = lazy(() =>
    import("@/features/teacher-authoring/TeacherAuthoringPage").then(
        (module) => ({ default: module.TeacherAuthoringPage }),
    ),
);
const TeacherDashboardPage = lazy(() =>
    import("@/features/teacher-dashboard/TeacherDashboardPage").then(
        (module) => ({ default: module.TeacherDashboardPage }),
    ),
);
const TeacherCoursePage = lazy(() =>
    import("@/features/teacher-course/TeacherCoursePage").then(
        (module) => ({ default: module.TeacherCoursePage }),
    ),
);
const TeacherCaseViewPage = lazy(() =>
    import("@/features/teacher-authoring/TeacherCaseViewPage").then(
        (module) => ({ default: module.TeacherCaseViewPage }),
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
const StudentDashboardPage = lazy(() =>
    import("@/features/student-dashboard/StudentDashboardPage").then((module) => ({
        default: module.StudentDashboardPage,
    })),
);
const StudentCaseResolutionPage = lazy(() =>
    import("@/features/student-runtime/StudentCaseResolutionPage").then((module) => ({
        default: module.StudentCaseResolutionPage,
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
                Cargando página...
            </span>
        </div>
    );
}

function App() {
    const location = useLocation();
    const isLandingRoute = location.pathname === "/";
    const isAdminDashboardRoute = location.pathname.startsWith("/admin/dashboard");
    const isTeacherShellRoute =
        location.pathname.startsWith("/teacher/dashboard") ||
        location.pathname.startsWith("/teacher/courses") ||
        location.pathname.startsWith("/teacher/cases") ||
        location.pathname.startsWith("/teacher/case-designer") ||
        location.pathname === "/teacher";
    const isStudentShellRoute =
        location.pathname.startsWith("/student/dashboard") ||
        location.pathname.startsWith("/student/cases") ||
        location.pathname === "/student";

    return (
        <ToastProvider>
        <div className="flex min-h-screen flex-col bg-bg-page font-sans type-body">
            {!isLandingRoute && !isAdminDashboardRoute && !isTeacherShellRoute && !isStudentShellRoute && <SiteHeader />}

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
                            path="/teacher/dashboard"
                            element={
                                <RequireRole role="teacher">
                                    <TeacherDashboardPage />
                                </RequireRole>
                            }
                        />
                        <Route
                            path="/teacher/courses/:courseId"
                            element={
                                <RequireRole role="teacher">
                                    <TeacherCoursePage />
                                </RequireRole>
                            }
                        />
                        <Route
                            path="/teacher/cases/:assignmentId"
                            element={
                                <RequireRole role="teacher">
                                    <TeacherCaseViewPage />
                                </RequireRole>
                            }
                        />
                        <Route
                            path="/teacher/cases/:assignmentId/entregas"
                            element={
                                <RequireRole role="teacher">
                                    <div className="flex flex-col items-center justify-center gap-4 px-4 py-24 text-center">
                                        <h1 className="text-xl font-semibold">Entregas del caso</h1>
                                        <p className="max-w-xs text-sm text-muted-foreground">
                                            El listado de entregas estará disponible en la próxima versión.
                                        </p>
                                    </div>
                                </RequireRole>
                            }
                        />
                        <Route path="/teacher" element={<Navigate to="/teacher/case-designer" replace />} />
                        <Route
                            path="/teacher/case-designer/*"
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
                            path="/student/dashboard"
                            element={
                                <RequireRole role="student">
                                    <StudentDashboardPage />
                                </RequireRole>
                            }
                        />
                        <Route
                            path="/student/cases/:assignmentId"
                            element={
                                <RequireRole role="student">
                                    <StudentCaseResolutionPage />
                                </RequireRole>
                            }
                        />
                        <Route path="/student" element={<Navigate to="/student/dashboard" replace />} />

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
                                    <AdminDashboardPage />
                                </RequireRole>
                            }
                        />

                        <Route path="/auth/callback" element={<AuthCallbackPage />} />
                        <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                </Suspense>
            </main>

        </div>
        </ToastProvider>
    );
}

export default App;

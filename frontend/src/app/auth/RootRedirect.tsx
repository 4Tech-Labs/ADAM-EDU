import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import { AppLanding } from "@/app/AppLanding";

/**
 * Handles the root route `/app/`.
 *
 * Redirect precedence (deterministic, per Issue #33):
 *  1. must_rotate_password=true      → /admin/change-password  (always wins)
 *  2. primary_role=university_admin  → /admin/dashboard (placeholder)
 *  3. primary_role=teacher           → /teacher
 *  4. primary_role=student           → /student
 *  5. no session or unknown role     → AppLanding (role entrypoints)
 */
export function RootRedirect() {
    const { session, actor, loading } = useAuth();

    if (loading) return null;
    if (!session) return <AppLanding />;

    if (actor?.must_rotate_password) {
        return <Navigate to="/admin/change-password" replace />;
    }

    switch (actor?.primary_role) {
        case "university_admin":
            return <Navigate to="/admin/dashboard" replace />;
        case "teacher":
            return <Navigate to="/teacher" replace />;
        case "student":
            return <Navigate to="/student" replace />;
        default:
            return <AppLanding />;
    }
}

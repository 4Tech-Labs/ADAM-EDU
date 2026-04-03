import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { ReactNode } from "react";

interface Props {
    children: ReactNode;
}

/**
 * Only allows navigation to the wrapped route when must_rotate_password is true.
 * Prevents accessing /admin/change-password when the flag is already cleared.
 */
export function RequirePasswordRotation({ children }: Props) {
    const { session, actor, loading } = useAuth();

    if (loading) return null;
    if (!session) return <Navigate to="/admin/login" replace />;
    if (!actor?.must_rotate_password) return <Navigate to="/" replace />;

    return <>{children}</>;
}

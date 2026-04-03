import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { ReactNode } from "react";

interface Props {
    children: ReactNode;
}

/**
 * Blocks unauthenticated access. Redirects to the root landing page (which
 * shows role-based entrypoints) when no session is present.
 *
 * Shows nothing while the auth bootstrap is in flight to avoid flash-of-wrong-route.
 */
export function RequireSession({ children }: Props) {
    const { session, loading } = useAuth();

    if (loading) return null;
    if (!session) return <Navigate to="/" replace />;

    return <>{children}</>;
}

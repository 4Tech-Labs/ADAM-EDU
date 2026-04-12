import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { MembershipSnapshot } from "./auth-types";
import type { ReactNode } from "react";

type Role = MembershipSnapshot["role"];

const ROLE_DASHBOARD: Record<Role, string> = {
    teacher: "/teacher/dashboard",
    student: "/student",
    university_admin: "/admin/dashboard",
};

interface Props {
    role: Role;
    children: ReactNode;
}

/**
 * Inverse of RequireRole: renders children only when the user is NOT
 * authenticated with the given role. If they already have an active
 * membership for that role, redirects them to the corresponding dashboard.
 *
 * Shows nothing while auth is bootstrapping to avoid flash-of-wrong-route.
 */
export function GuestOnlyRoute({ role, children }: Props) {
    const { session, actor, loading } = useAuth();

    if (loading) return null;

    if (session && actor) {
        const hasRole = actor.memberships.some(
            (m) => m.role === role && m.status === "active",
        );
        if (hasRole) {
            return <Navigate to={ROLE_DASHBOARD[role]} replace />;
        }
    }

    return <>{children}</>;
}

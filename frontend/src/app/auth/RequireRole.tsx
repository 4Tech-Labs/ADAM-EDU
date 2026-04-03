import { Navigate } from "react-router-dom";
import { useAuth } from "./useAuth";
import type { MembershipSnapshot } from "./auth-types";
import type { ReactNode } from "react";

type Role = MembershipSnapshot["role"];

const ROLE_LOGIN_PATH: Record<Role, string> = {
    teacher: "/teacher/login",
    student: "/student/login",
    university_admin: "/admin/login",
};

interface Props {
    role: Role;
    children: ReactNode;
}

/**
 * Authorizes by active membership, NOT by primary_role alone.
 *
 * Redirect precedence (non-negotiable per Issue #33):
 *  1. must_rotate_password=true  → /admin/change-password (always wins)
 *  2. no session                 → role-specific login page
 *  3. no active membership       → root landing
 */
export function RequireRole({ role, children }: Props) {
    const { session, actor, loading } = useAuth();

    if (loading) return null;

    if (!session) {
        return <Navigate to={ROLE_LOGIN_PATH[role]} replace />;
    }

    if (actor?.must_rotate_password) {
        return <Navigate to="/admin/change-password" replace />;
    }

    const hasRole = actor?.memberships.some(
        (m) => m.role === role && m.status === "active",
    );

    if (!hasRole) {
        return <Navigate to="/" replace />;
    }

    return <>{children}</>;
}

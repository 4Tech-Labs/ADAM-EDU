import type { Session } from "@supabase/supabase-js";

export type { Session };

export interface MembershipSnapshot {
    id: string;
    university_id: string;
    role: "teacher" | "student" | "university_admin";
    status: "active" | "suspended";
    must_rotate_password: boolean;
}

/** Mirrors the shape returned by GET /api/auth/me */
export interface AuthMeActor {
    auth_user_id: string;
    profile: { id: string; full_name: string };
    memberships: MembershipSnapshot[];
    must_rotate_password: boolean;
    primary_role: "teacher" | "student" | "university_admin";
}

export interface AuthContextValue {
    session: Session | null;
    actor: AuthMeActor | null;
    loading: boolean;
    error: string | null;
    signOut: () => Promise<void>;
    refreshActor: () => Promise<void>;
}

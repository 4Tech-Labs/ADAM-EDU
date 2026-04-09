/**
 * Short-lived activation context stored in sessionStorage.
 *
 * Used to carry invite_token or course_access_token across an OAuth redirect without placing it
 * in the URL, OAuth state param, localStorage, or any server-side store.
 *
 * TTL is hard-coded at 5 minutes. Expired contexts are silently dropped and
 * treated as non-existent. The token is cleared by AuthCallbackPage after
 * the activation flow completes (success or terminal error).
 *
 * Tokens MUST NOT appear in query strings, path params, OAuth state,
 * breadcrumbs, or logs at any point.
 */

import type { ActivationContext } from "./adam-types";

const STORAGE_KEY = "adam_activation_ctx";
const TTL_MS = 5 * 60 * 1000;

type ActivationContextInput =
    | {
        flow: "teacher_activate";
        token_kind: "invite";
        invite_token: string;
        role: "teacher";
    }
    | {
        flow: "student_join_invite";
        token_kind: "invite";
        invite_token: string;
        role: "student";
    }
    | {
        flow: "student_join_course_access";
        token_kind: "course_access";
        course_access_token: string;
        auth_path?: "oauth" | "password_sign_in";
    };

export function saveActivationContext(
    ctx: ActivationContextInput,
): void {
    const value: ActivationContext = {
        ...ctx,
        expires_at: Date.now() + TTL_MS,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

export function readActivationContext(): ActivationContext | null {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    try {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        const ctx = normalizeActivationContext(parsed);
        if (!ctx) {
            sessionStorage.removeItem(STORAGE_KEY);
            return null;
        }
        if (Date.now() > ctx.expires_at) {
            sessionStorage.removeItem(STORAGE_KEY);
            return null;
        }
        return ctx;
    } catch {
        sessionStorage.removeItem(STORAGE_KEY);
        return null;
    }
}

export function clearActivationContext(): void {
    sessionStorage.removeItem(STORAGE_KEY);
}

function normalizeActivationContext(raw: Record<string, unknown>): ActivationContext | null {
    const expiresAt = typeof raw.expires_at === "number" ? raw.expires_at : null;
    if (expiresAt === null) return null;

    if (
        raw.flow === "teacher_activate"
        && typeof raw.invite_token === "string"
        && raw.role === "teacher"
    ) {
        return {
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: raw.invite_token,
            role: "teacher",
            expires_at: expiresAt,
        };
    }

    if (
        (raw.flow === "student_join" || raw.flow === "student_join_invite")
        && typeof raw.invite_token === "string"
        && raw.role === "student"
    ) {
        return {
            flow: "student_join_invite",
            token_kind: "invite",
            invite_token: raw.invite_token,
            role: "student",
            expires_at: expiresAt,
        };
    }

    if (
        raw.flow === "student_join_course_access"
        && typeof raw.course_access_token === "string"
    ) {
        const authPath =
            raw.auth_path === "oauth" || raw.auth_path === "password_sign_in"
                ? raw.auth_path
                : undefined;
        return {
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: raw.course_access_token,
            auth_path: authPath,
            expires_at: expiresAt,
        };
    }

    return null;
}

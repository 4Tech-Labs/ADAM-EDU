/**
 * Short-lived activation context stored in sessionStorage.
 *
 * Used to carry invite_token across an OAuth redirect without placing it
 * in the URL, OAuth state param, localStorage, or any server-side store.
 *
 * TTL is hard-coded at 5 minutes. Expired contexts are silently dropped and
 * treated as non-existent. The token is cleared by AuthCallbackPage after
 * the activation flow completes (success or terminal error).
 *
 * invite_token MUST NOT appear in query strings, path params, OAuth state,
 * breadcrumbs, or logs at any point.
 */

const STORAGE_KEY = "adam_activation_ctx";
const TTL_MS = 5 * 60 * 1000;

interface ActivationContext {
    flow: "teacher_activate" | "student_join";
    invite_token: string;
    role: "teacher" | "student";
    expires_at: number; // epoch ms
}

export function saveActivationContext(
    ctx: Omit<ActivationContext, "expires_at">,
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
        const ctx = JSON.parse(raw) as ActivationContext;
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

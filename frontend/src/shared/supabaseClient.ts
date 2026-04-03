/**
 * Supabase client — auth and session management ONLY.
 * Never use this client for domain queries. PostgREST is not in scope.
 *
 * Single lazy-initialized instance shared across the entire frontend.
 * AuthProvider, getBearerToken(), and any other auth consumer must import
 * getSupabaseClient() from this module — never call createClient() directly.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null | undefined;

export function getSupabaseClient(): SupabaseClient | null {
    if (_client !== undefined) {
        return _client;
    }

    if (typeof window === "undefined") {
        _client = null;
        return null;
    }

    const url = import.meta.env.VITE_SUPABASE_URL?.trim();
    const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim();

    if (!url || !anonKey) {
        _client = null;
        return null;
    }

    _client = createClient(url, anonKey, {
        auth: {
            flowType: "pkce",
            autoRefreshToken: true,
            persistSession: true,
        },
    });

    return _client;
}

/** For use in tests only — resets the singleton so env mocks take effect. */
export function resetSupabaseClientForTests(): void {
    _client = undefined;
}

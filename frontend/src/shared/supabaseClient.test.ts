import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getSupabaseClient, resetSupabaseClientForTests } from "./supabaseClient";

vi.mock("@supabase/supabase-js", () => ({
    createClient: vi.fn(() => ({ isMockClient: true })),
}));

describe("getSupabaseClient", () => {
    const originalEnv = import.meta.env;

    beforeEach(() => {
        resetSupabaseClientForTests();
    });

    afterEach(() => {
        resetSupabaseClientForTests();
        vi.unstubAllEnvs();
    });

    it("returns null when VITE_SUPABASE_URL is missing", () => {
        vi.stubEnv("VITE_SUPABASE_URL", "");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-key");
        expect(getSupabaseClient()).toBeNull();
    });

    it("returns null when VITE_SUPABASE_ANON_KEY is missing", () => {
        vi.stubEnv("VITE_SUPABASE_URL", "http://localhost:54321");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
        expect(getSupabaseClient()).toBeNull();
    });

    it("returns a client when env vars are present", () => {
        vi.stubEnv("VITE_SUPABASE_URL", "http://localhost:54321");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
        const client = getSupabaseClient();
        expect(client).not.toBeNull();
    });

    it("returns the same instance on repeated calls (singleton)", () => {
        vi.stubEnv("VITE_SUPABASE_URL", "http://localhost:54321");
        vi.stubEnv("VITE_SUPABASE_ANON_KEY", "test-anon-key");
        const first = getSupabaseClient();
        const second = getSupabaseClient();
        expect(first).toBe(second);
    });

    // Suppress unused-var warning — originalEnv is needed to satisfy no-unused-vars but
    // the actual restore is handled by vi.unstubAllEnvs().
    void originalEnv;
});

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
    saveActivationContext,
    readActivationContext,
    clearActivationContext,
} from "./activationContext";

describe("activationContext", () => {
    beforeEach(() => {
        sessionStorage.clear();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("save → read returns the correct value", () => {
        saveActivationContext({
            flow: "teacher_activate",
            invite_token: "tok_abc123",
            role: "teacher",
        });

        const ctx = readActivationContext();
        expect(ctx).not.toBeNull();
        expect(ctx?.flow).toBe("teacher_activate");
        expect(ctx?.invite_token).toBe("tok_abc123");
        expect(ctx?.role).toBe("teacher");
        expect(typeof ctx?.expires_at).toBe("number");
    });

    it("returns null when nothing is stored", () => {
        expect(readActivationContext()).toBeNull();
    });

    it("clearActivationContext removes the stored context", () => {
        saveActivationContext({
            flow: "student_join",
            invite_token: "tok_xyz",
            role: "student",
        });
        clearActivationContext();
        expect(readActivationContext()).toBeNull();
    });

    it("returns null and removes the entry when TTL has expired", () => {
        vi.useFakeTimers();
        saveActivationContext({
            flow: "teacher_activate",
            invite_token: "tok_expired",
            role: "teacher",
        });

        // Advance clock past the 5-minute TTL
        vi.advanceTimersByTime(5 * 60 * 1000 + 1);

        expect(readActivationContext()).toBeNull();
        // The key must be cleaned up
        expect(sessionStorage.getItem("adam_activation_ctx")).toBeNull();
    });

    it("returns null and removes the entry for malformed JSON", () => {
        sessionStorage.setItem("adam_activation_ctx", "{invalid-json}");
        expect(readActivationContext()).toBeNull();
        expect(sessionStorage.getItem("adam_activation_ctx")).toBeNull();
    });
});

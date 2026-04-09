import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    clearActivationContext,
    readActivationContext,
    saveActivationContext,
} from "./activationContext";

describe("activationContext", () => {
    beforeEach(() => {
        sessionStorage.clear();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("save and read preserves invite activation context", () => {
        saveActivationContext({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok_abc123",
            role: "teacher",
        });

        const ctx = readActivationContext();
        expect(ctx).not.toBeNull();
        expect(ctx).toEqual({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok_abc123",
            role: "teacher",
            expires_at: expect.any(Number),
        });
    });

    it("save and read preserves course access context", () => {
        saveActivationContext({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course_tok_123",
        });

        const ctx = readActivationContext();
        expect(ctx).not.toBeNull();
        expect(ctx).toEqual({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course_tok_123",
            expires_at: expect.any(Number),
        });
    });

    it("normalizes the legacy student_join invite shape", () => {
        sessionStorage.setItem(
            "adam_activation_ctx",
            JSON.stringify({
                flow: "student_join",
                invite_token: "legacy_tok",
                role: "student",
                expires_at: Date.now() + 1000,
            }),
        );

        const ctx = readActivationContext();
        expect(ctx).toEqual({
            flow: "student_join_invite",
            token_kind: "invite",
            invite_token: "legacy_tok",
            role: "student",
            expires_at: expect.any(Number),
        });
    });

    it("clearActivationContext removes the stored context", () => {
        saveActivationContext({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course_tok_xyz",
        });

        clearActivationContext();

        expect(readActivationContext()).toBeNull();
    });

    it("returns null and removes the entry when TTL has expired", () => {
        vi.useFakeTimers();
        saveActivationContext({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok_expired",
            role: "teacher",
        });

        vi.advanceTimersByTime(5 * 60 * 1000 + 1);

        expect(readActivationContext()).toBeNull();
        expect(sessionStorage.getItem("adam_activation_ctx")).toBeNull();
    });

    it("returns null and removes malformed payloads", () => {
        sessionStorage.setItem("adam_activation_ctx", "{invalid-json}");

        expect(readActivationContext()).toBeNull();
        expect(sessionStorage.getItem("adam_activation_ctx")).toBeNull();
    });
});

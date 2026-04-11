import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/shared/testing/msw/server";

describe("shared testing msw server", () => {
    it("intercepts handled API requests", async () => {
        server.use(
            http.get("/api/test/health", () =>
                HttpResponse.json({ ok: true }),
            ),
        );

        const response = await fetch("/api/test/health");
        const body = (await response.json()) as { ok: boolean };

        expect(body.ok).toBe(true);
    });

    it("fails fast on unhandled API requests", async () => {
        const response = await fetch("/api/test/unhandled");
        const body = (await response.json()) as { message: string };

        expect(response.status).toBe(500);
        expect(body.message).toMatch(/Unhandled API request in test/i);
    });
});

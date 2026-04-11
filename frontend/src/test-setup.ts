import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "@/shared/testing/msw/server";

beforeAll(() => {
    server.listen({
        onUnhandledRequest(request) {
            const { pathname } = new URL(request.url);
            if (pathname.startsWith("/api/")) {
                throw new Error(`Unhandled API request in test: ${request.method} ${request.url}`);
            }
        },
    });
});

afterEach(() => {
    cleanup();
    server.resetHandlers();
});

afterAll(() => {
    server.close();
});

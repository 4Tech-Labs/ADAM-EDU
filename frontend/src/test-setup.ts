import { setMaxListeners } from "node:events";
import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "@/shared/testing/msw/server";

// MSW 2's network stack can fan out abort listeners through rettime during the
// full suite. Keep a warning ceiling in place, but raise it above Node's default
// so test infrastructure noise doesn't drown real app-level failures.
setMaxListeners(50);

// jsdom does not implement window.scrollTo; silence the "not implemented" error
// so that it does not interrupt synchronous event handlers under test.
Object.defineProperty(window, "scrollTo", { value: vi.fn(), writable: true });

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

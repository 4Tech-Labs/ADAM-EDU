import type { RequestHandler } from "msw";

/**
 * Base handlers for shared test infrastructure.
 *
 * Start intentionally minimal. Tests should opt into the specific HTTP contract
 * they need with `server.use(...)` instead of depending on a hidden global stub.
 */
export const handlers: RequestHandler[] = [];

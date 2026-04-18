import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { renderWithProviders } from "@/shared/test-utils";
import { server } from "@/shared/testing/msw/server";

import { AuthoringForm } from "./AuthoringForm";

type DeferredHttpResponse =
    | ReturnType<typeof HttpResponse.json>
    | ReturnType<typeof HttpResponse.text>;

function createDeferredResponse() {
    let resolve!: (response: DeferredHttpResponse) => void;
    const promise = new Promise<DeferredHttpResponse>((res) => {
        resolve = res;
    });

    return { promise, resolve };
}

async function selectOption(
    user: ReturnType<typeof userEvent.setup>,
    label: RegExp,
    option: RegExp,
) {
    await user.click(screen.getByLabelText(label));
    await user.click(await screen.findByRole("option", { name: option }));
}

async function enableSuggestions(user: ReturnType<typeof userEvent.setup>) {
    await selectOption(user, /asignatura/i, /gerencia/i);
    await user.click(screen.getByLabelText(/grupo 01/i));
    await selectOption(user, /m[oó]dulo del syllabus/i, /fundamentos/i);
}

async function showTechniquesSection(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("radio", { name: /caso .*an[aá]lisis de datos/i }));
}

describe("AuthoringForm", () => {
    beforeAll(() => {
        Element.prototype.hasPointerCapture ??= () => false;
        Element.prototype.releasePointerCapture ??= () => {};
        Element.prototype.setPointerCapture ??= () => {};
        Element.prototype.scrollIntoView ??= () => {};
    });

    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it("fills scenario fields from the scenario mutation and shows loading state", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", async () => deferred.promise),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Escenario sugerido",
                guidingQuestion: "Pregunta sugerida",
                suggestedTechniques: [],
            }),
        );

        expect(await screen.findByDisplayValue("Escenario sugerido")).toBeInTheDocument();
        expect(screen.getByDisplayValue("Pregunta sugerida")).toBeInTheDocument();
    }, 20_000);

    it("fills suggested techniques from the techniques mutation and clears the stale warning", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", async ({ request }) => {
                const body = (await request.json()) as { intent: string };
                if (body.intent === "techniques") {
                    return deferred.promise;
                }

                return HttpResponse.json({
                    scenarioDescription: "",
                    guidingQuestion: "",
                    suggestedTechniques: [],
                });
            }),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);
        await showTechniquesSection(user);

        const button = screen.getByRole("button", { name: /sugerir t[ée]cnicas de an[aá]lisis/i });
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "",
                guidingQuestion: "",
                suggestedTechniques: ["Árboles de decisión", "Clustering"],
            }),
        );

        expect(await screen.findByText("Árboles de decisión")).toBeInTheDocument();
        expect(screen.getByText("Clustering")).toBeInTheDocument();
        expect(
            screen.queryByText(/podr[ií]an estar desactualizadas/i),
        ).not.toBeInTheDocument();
    }, 20_000);

    it("prevents duplicate scenario requests on rapid double click", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();
        const requestCounter = vi.fn(() => deferred.promise);

        server.use(
            http.post("/api/suggest", () => requestCounter()),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);
        await user.click(button);

        await waitFor(() => {
            expect(button).toBeDisabled();
        });
        expect(requestCounter).toHaveBeenCalledTimes(1);

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Escenario único",
                guidingQuestion: "Pregunta única",
                suggestedTechniques: [],
            }),
        );

        expect(await screen.findByDisplayValue("Escenario único")).toBeInTheDocument();
    });

    it("shows the mutation error and re-enables the button after failure", async () => {
        const user = userEvent.setup();

        server.use(
            http.post("/api/suggest", () => HttpResponse.text("Fallo de red controlado", { status: 500 })),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        const button = screen.getByRole("button", { name: /sugerir caso y dilema/i });
        await user.click(button);

        expect(await screen.findByText(/fallo de red controlado/i)).toBeInTheDocument();
        await waitFor(() => {
            expect(button).not.toBeDisabled();
        });
    });

    it("ignores a stale scenario response after the teacher changes context", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();

        server.use(
            http.post("/api/suggest", () => deferred.promise),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        await selectOption(user, /industria/i, /retail/i);

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "Respuesta vieja",
                guidingQuestion: "Pregunta vieja",
                suggestedTechniques: [],
            }),
        );

        await waitFor(() => {
            expect(screen.queryByDisplayValue("Respuesta vieja")).not.toBeInTheDocument();
        });
        expect(screen.getByLabelText(/industria/i)).toHaveTextContent(/retail/i);
    }, 20_000);

    it("ignores a stale response after clearing the form and resets visible mutation errors", async () => {
        const user = userEvent.setup();
        const deferred = createDeferredResponse();
        let requestCount = 0;

        server.use(
            http.post("/api/suggest", () => {
                requestCount += 1;
                if (requestCount === 1) {
                    return HttpResponse.text("Error transitorio", { status: 500 });
                }
                return deferred.promise;
            }),
        );

        renderWithProviders(<AuthoringForm onSubmit={vi.fn()} />);
        await enableSuggestions(user);

        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        expect(await screen.findByText(/error transitorio/i)).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: /limpiar todo/i }));
        await waitFor(() => {
            expect(screen.queryByText(/error transitorio/i)).not.toBeInTheDocument();
        });

        await enableSuggestions(user);
        await user.click(screen.getByRole("button", { name: /sugerir caso y dilema/i }));
        await user.click(screen.getByRole("button", { name: /limpiar todo/i }));

        deferred.resolve(
            HttpResponse.json({
                scenarioDescription: "No debe aplicar",
                guidingQuestion: "No debe aplicar",
                suggestedTechniques: [],
            }),
        );

        await waitFor(() => {
            expect(screen.queryByDisplayValue("No debe aplicar")).not.toBeInTheDocument();
        });
    }, 20_000);
});

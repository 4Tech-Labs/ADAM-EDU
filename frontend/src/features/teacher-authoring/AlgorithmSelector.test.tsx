/**
 * Issue #230 — AlgorithmSelector component tests.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";
import { server } from "@/shared/testing/msw/server";

import { AlgorithmSelector, type AlgorithmSelectorProps } from "./AlgorithmSelector";

function defaultProps(overrides: Partial<AlgorithmSelectorProps> = {}): AlgorithmSelectorProps {
    return {
        profile: "ml_ds",
        caseType: "harvard_with_eda",
        mode: "single",
        primary: null,
        challenger: null,
        onChange: vi.fn(),
        onSuggest: vi.fn(),
        isSuggestPending: false,
        canSuggest: true,
        hasError: false,
        ...overrides,
    };
}

const fullCatalog = {
    profile: "ml_ds",
    case_type: "harvard_with_eda",
    items: [
        { name: "Regresión Lineal", family: "regresion", family_label: "Regresión", tier: "baseline" },
        { name: "Random Forest Regressor", family: "regresion", family_label: "Regresión", tier: "challenger" },
        { name: "Árboles de decisión", family: "clasificacion", family_label: "Clasificación", tier: "baseline" },
        { name: "XGBoost", family: "clasificacion", family_label: "Clasificación", tier: "challenger" },
    ],
};

const businessCatalog = {
    profile: "business",
    case_type: "harvard_with_eda",
    items: [
        { name: "Regresión Lineal", family: "regresion", family_label: "Regresión", tier: "baseline" },
        { name: "K-Means", family: "clustering", family_label: "Clustering", tier: "baseline" },
    ],
};

beforeAll(() => {
    Element.prototype.hasPointerCapture ??= () => false;
    Element.prototype.releasePointerCapture ??= () => {};
    Element.prototype.setPointerCapture ??= () => {};
    Element.prototype.scrollIntoView ??= () => {};
});

describe("AlgorithmSelector (Issue #230)", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it("renders the suggest button and the mode toggle in single mode", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));

        renderWithProviders(<AlgorithmSelector {...defaultProps()} />);

        expect(
            await screen.findByRole("button", { name: /sugerir algoritmos con adam/i }),
        ).toBeInTheDocument();
        const radios = screen.getAllByRole("radio");
        expect(radios).toHaveLength(2);
        expect(radios[0]).toHaveAttribute("aria-checked", "true");
    });

    it("renders both baseline and challenger selects in contrast mode", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));

        renderWithProviders(<AlgorithmSelector {...defaultProps({ mode: "contrast" })} />);

        await screen.findByLabelText(/baseline \(interpretable\)/i);
        expect(screen.getByLabelText(/challenger \(alta capacidad\)/i)).toBeInTheDocument();
    });

    it("disables the contrast option when the catalog has no challengers", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(businessCatalog)));

        renderWithProviders(<AlgorithmSelector {...defaultProps({ profile: "business" })} />);

        await waitFor(() => {
            const radios = screen.getAllByRole("radio");
            expect(radios[1]).toBeDisabled();
        });
    });

    it("invokes onSuggest when the suggest button is clicked", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));
        const user = userEvent.setup();
        const onSuggest = vi.fn();

        renderWithProviders(<AlgorithmSelector {...defaultProps({ onSuggest })} />);

        const button = await screen.findByRole("button", { name: /sugerir algoritmos con adam/i });
        await user.click(button);
        expect(onSuggest).toHaveBeenCalledTimes(1);
    });

    it("shows an inline error when baseline equals challenger in contrast mode", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));

        renderWithProviders(
            <AlgorithmSelector
                {...defaultProps({
                    mode: "contrast",
                    primary: "Regresión Lineal",
                    challenger: "Regresión Lineal",
                })}
            />,
        );

        expect(
            await screen.findByText(/no pueden ser el mismo algoritmo/i),
        ).toBeInTheDocument();
    });

    it("renders the retry banner when the catalog query fails", async () => {
        server.use(
            http.get("/api/authoring/algorithm-catalog", () =>
                HttpResponse.json({ detail: "boom" }, { status: 500 }),
            ),
        );

        renderWithProviders(<AlgorithmSelector {...defaultProps()} />);

        expect(
            await screen.findByText(/no se pudo cargar el catálogo/i),
        ).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /reintentar/i })).toBeInTheDocument();
    });

    it("auto-coerces mode to 'single' when a contrast pre-set lands on an empty challenger catalog", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(businessCatalog)));
        const onChange = vi.fn();

        renderWithProviders(
            <AlgorithmSelector
                {...defaultProps({
                    profile: "business",
                    mode: "contrast",
                    challenger: "XGBoost",
                    onChange,
                })}
            />,
        );

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledWith(
                expect.objectContaining({ mode: "single", challenger: null }),
            );
        });
    });

    it("filters challengers to the same family as the selected baseline", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));

        renderWithProviders(
            <AlgorithmSelector
                {...defaultProps({
                    mode: "contrast",
                    primary: "Regresión Lineal",
                })}
            />,
        );

        // Family pill on the challenger label.
        await screen.findByLabelText(/challenger \(alta capacidad\) · Regresión/i);
    });

    it("resets the challenger when the baseline family changes", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));
        const onChange = vi.fn();

        // Baseline = Regresión Lineal (regresion family); Challenger = XGBoost
        // (clasificacion family) is now invalid — the effect should clear it.
        renderWithProviders(
            <AlgorithmSelector
                {...defaultProps({
                    mode: "contrast",
                    primary: "Regresión Lineal",
                    challenger: "XGBoost",
                    onChange,
                })}
            />,
        );

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledWith(
                expect.objectContaining({ mode: "contrast", challenger: null }),
            );
        });
    });

    it("disables the suggest button while the suggest mutation is pending", async () => {
        server.use(http.get("/api/authoring/algorithm-catalog", () => HttpResponse.json(fullCatalog)));

        renderWithProviders(<AlgorithmSelector {...defaultProps({ isSuggestPending: true })} />);

        const button = await screen.findByRole("button", { name: /sugerir algoritmos con adam/i });
        expect(button).toBeDisabled();
    });
});

import { screen } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { useAuth } from "@/app/auth/useAuth";
import type { AuthContextValue } from "@/app/auth/auth-types";
import {
    createTestQueryClient,
    createWrapper,
    renderWithProviders,
} from "@/shared/test-utils";

const authValue: AuthContextValue = {
    session: null,
    actor: null,
    loading: false,
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

describe("test-utils", () => {
    it("creates isolated query clients with test-safe defaults", () => {
        const first = createTestQueryClient();
        const second = createTestQueryClient();

        expect(first).not.toBe(second);
        expect(first.getDefaultOptions().queries?.retry).toBe(false);
        expect(first.getDefaultOptions().queries?.gcTime).toBe(0);
        expect(first.getDefaultOptions().queries?.staleTime).toBe(0);
        expect(first.getDefaultOptions().mutations?.retry).toBe(false);
    });

    it("renderWithProviders wires QueryClientProvider, MemoryRouter, and auth context", async () => {
        function Probe() {
            const { loading } = useAuth();
            const location = useLocation();
            const { data } = useQuery({
                queryKey: ["probe"],
                queryFn: async () => "resolved",
            });

            return (
                <>
                    <span data-testid="pathname">{location.pathname}</span>
                    <span data-testid="loading">{String(loading)}</span>
                    <span data-testid="query-data">{data ?? "pending"}</span>
                </>
            );
        }

        const { queryClient } = renderWithProviders(<Probe />, {
            initialEntries: ["/admin/dashboard"],
            authValue,
        });

        expect(screen.getByTestId("pathname").textContent).toBe("/admin/dashboard");
        expect(screen.getByTestId("loading").textContent).toBe("false");

        await waitFor(() => {
            expect(screen.getByTestId("query-data").textContent).toBe("resolved");
        });
        expect(queryClient.getQueryData(["probe"])).toBe("resolved");
    });

    it("createWrapper works with renderHook", async () => {
        const wrapper = createWrapper();
        const { result } = renderHook(
            () =>
                useQuery({
                    queryKey: ["hook-probe"],
                    queryFn: async () => 7,
                }),
            { wrapper },
        );

        await waitFor(() => {
            expect(result.current.data).toBe(7);
        });
    });

    it("supports strict mode composition", async () => {
        const queryClient = createTestQueryClient();
        const queryFn = vi.fn().mockResolvedValue("ok");

        function Probe() {
            const { data } = useQuery({
                queryKey: ["strict-probe"],
                queryFn,
            });

            return <span data-testid="strict-data">{data ?? "pending"}</span>;
        }

        renderWithProviders(<Probe />, {
            queryClient,
            strictMode: true,
        });

        await waitFor(() => {
            expect(screen.getByTestId("strict-data").textContent).toBe("ok");
        });
        expect(queryFn).toHaveBeenCalled();
    });
});

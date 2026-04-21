import { StrictMode, type ReactElement, type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { AuthContext } from "@/app/auth/auth-context";
import type { AuthContextValue } from "@/app/auth/auth-types";
import { ToastProvider } from "@/shared/Toast";

export function createTestQueryClient(): QueryClient {
    return new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
                gcTime: 0,
                staleTime: 0,
            },
            mutations: {
                retry: false,
            },
        },
    });
}

interface WrapperOptions {
    queryClient?: QueryClient;
    initialEntries?: string[];
    strictMode?: boolean;
    authValue?: AuthContextValue;
}

export function createWrapper(options: WrapperOptions = {}) {
    const queryClient = options.queryClient ?? createTestQueryClient();
    const initialEntries = options.initialEntries ?? ["/"];
    const strictMode = options.strictMode ?? false;
    const authValue = options.authValue;

    return function Wrapper({ children }: { children: ReactNode }) {
        const innerContent = authValue ? (
            <AuthContext.Provider value={authValue}>
                {children}
            </AuthContext.Provider>
        ) : (
            children
        );

        const content = (
            <ToastProvider>
            <MemoryRouter initialEntries={initialEntries}>
                <QueryClientProvider client={queryClient}>
                    {innerContent}
                </QueryClientProvider>
            </MemoryRouter>
            </ToastProvider>
        );

        return strictMode ? <StrictMode>{content}</StrictMode> : content;
    };
}

type RenderWithProvidersOptions = WrapperOptions &
    Omit<RenderOptions, "wrapper">;

export function renderWithProviders(
    ui: ReactElement,
    options: RenderWithProvidersOptions = {},
) {
    const { queryClient, initialEntries, strictMode, authValue, ...renderOptions } =
        options;
    const testQueryClient = queryClient ?? createTestQueryClient();

    return {
        ...render(ui, {
            wrapper: createWrapper({
                queryClient: testQueryClient,
                initialEntries,
                strictMode,
                authValue,
            }),
            ...renderOptions,
        }),
        queryClient: testQueryClient,
    };
}

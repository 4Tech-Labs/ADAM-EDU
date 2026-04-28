import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/queryKeys";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { ApiError, apiFetch } from "@/shared/api";

import type { AuthMeActor, Session } from "./auth-types";
import { AuthContext } from "./auth-context";

const ACTOR_PROFILE_ERROR =
    "No se pudo cargar tu perfil. Intenta iniciar sesión de nuevo.";

export function AuthProvider({ children }: { children: ReactNode }) {
    const queryClient = useQueryClient();
    const [session, setSession] = useState<Session | null>(null);
    const [bootstrapComplete, setBootstrapComplete] = useState(false);
    const [bootstrapError, setBootstrapError] = useState<string | null>(null);
    const [actorQueryEnabled, setActorQueryEnabled] = useState(false);

    const fetchActorOrThrow = useCallback(async (): Promise<AuthMeActor> => {
        try {
            const res = await apiFetch("/auth/me");
            return (await res.json()) as AuthMeActor;
        } catch (error) {
            if (error instanceof ApiError && error.status === 401) {
                setSession(null);
                setBootstrapError(null);
                setActorQueryEnabled(false);

                const supabase = getSupabaseClient();
                if (supabase) {
                    void supabase.auth.signOut();
                }
            }

            throw error;
        }
    }, []);

    const actorQuery = useQuery({
        queryKey: queryKeys.auth.actor(),
        queryFn: fetchActorOrThrow,
        enabled: bootstrapComplete && !!session && actorQueryEnabled,
        staleTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: false,
    });

    const actor = actorQuery.data ?? null;
    const loading =
        !bootstrapComplete ||
        (!!session && actorQuery.isPending && !actorQuery.data);
    const error =
        bootstrapError ??
        (session && !actor && actorQuery.isError ? ACTOR_PROFILE_ERROR : null);

    const refreshActor = useCallback(async () => {
        if (!session) {
            queryClient.removeQueries({ queryKey: queryKeys.auth.actor() });
            return;
        }

        await queryClient.fetchQuery({
            queryKey: queryKeys.auth.actor(),
            queryFn: fetchActorOrThrow,
            staleTime: 0,
        });
    }, [fetchActorOrThrow, queryClient, session]);

    useEffect(() => {
        const supabase = getSupabaseClient();
        if (!supabase) {
            setBootstrapComplete(true);
            return;
        }
        const auth = supabase.auth;

        let actorRefreshTimeoutId: number | null = null;

        async function bootstrap() {
            const { data, error: sessionError } = await auth.getSession();

            if (sessionError) {
                setBootstrapError(sessionError.message);
                setActorQueryEnabled(false);
                setBootstrapComplete(true);
                return;
            }

            setBootstrapError(null);
            setSession(data.session ?? null);
            setActorQueryEnabled(!!data.session);
            setBootstrapComplete(true);
        }

        void bootstrap();

        const { data: listenerData } = auth.onAuthStateChange(
            (event, nextSession) => {
                if (event === "SIGNED_IN") {
                    setSession(nextSession);
                    setBootstrapError(null);
                    setActorQueryEnabled(false);

                    if (nextSession) {
                        // Defer invalidation to the next macrotask so apiFetch()
                        // does not re-enter Supabase getSession() while the PKCE
                        // storage lock is still held inside onAuthStateChange.
                        actorRefreshTimeoutId = window.setTimeout(() => {
                            setActorQueryEnabled(true);
                            void queryClient.fetchQuery({
                                queryKey: queryKeys.auth.actor(),
                                queryFn: fetchActorOrThrow,
                                staleTime: 0,
                            });
                        }, 0);
                    }

                    return;
                }

                if (
                    event === "INITIAL_SESSION" ||
                    event === "TOKEN_REFRESHED"
                ) {
                    setSession(nextSession);
                    setBootstrapError(null);
                    setActorQueryEnabled(!!nextSession);
                    return;
                }

                if (event === "SIGNED_OUT") {
                    setSession(null);
                    setBootstrapError(null);
                    setActorQueryEnabled(false);
                    queryClient.clear();
                }
            },
        );

        return () => {
            if (actorRefreshTimeoutId !== null) {
                window.clearTimeout(actorRefreshTimeoutId);
            }
            listenerData.subscription.unsubscribe();
        };
    }, [fetchActorOrThrow, queryClient]);

    const signOut = useCallback(async () => {
        const supabase = getSupabaseClient();
        if (supabase) {
            await supabase.auth.signOut();
        }

        setSession(null);
        setBootstrapError(null);
        setActorQueryEnabled(false);
        queryClient.clear();
    }, [queryClient]);

    return (
        <AuthContext.Provider
            value={{ session, actor, loading, error, signOut, refreshActor }}
        >
            {children}
        </AuthContext.Provider>
    );
}

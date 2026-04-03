import {
    createContext,
    useCallback,
    useEffect,
    useState,
    type ReactNode,
} from "react";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { apiFetch } from "@/shared/api";
import type { AuthContextValue, AuthMeActor, Session } from "./auth-types";

export const AuthContext = createContext<AuthContextValue | undefined>(
    undefined,
);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState<Session | null>(null);
    const [actor, setActor] = useState<AuthMeActor | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchActor = useCallback(async (): Promise<AuthMeActor | null> => {
        try {
            const res = await apiFetch("/auth/me");
            return (await res.json()) as AuthMeActor;
        } catch {
            return null;
        }
    }, []);

    const refreshActor = useCallback(async () => {
        const next = await fetchActor();
        setActor(next);
    }, [fetchActor]);

    useEffect(() => {
        const supabase = getSupabaseClient();
        if (!supabase) {
            setLoading(false);
            return;
        }

        let cancelled = false;

        async function bootstrap() {
            const { data, error: sessionError } =
                await supabase!.auth.getSession();

            if (cancelled) return;

            if (sessionError) {
                setError(sessionError.message);
                setLoading(false);
                return;
            }

            const currentSession = data.session ?? null;
            setSession(currentSession);

            if (currentSession) {
                const resolvedActor = await fetchActor();
                if (!cancelled) {
                    setActor(resolvedActor);
                    if (!resolvedActor) {
                        setError(
                            "No se pudo cargar tu perfil. Intenta iniciar sesión de nuevo.",
                        );
                    }
                }
            }

            if (!cancelled) {
                setLoading(false);
            }
        }

        void bootstrap();

        const { data: listenerData } = supabase.auth.onAuthStateChange(
            async (event, nextSession) => {
                if (cancelled) return;

                if (
                    event === "SIGNED_IN" ||
                    event === "TOKEN_REFRESHED" ||
                    event === "INITIAL_SESSION"
                ) {
                    setSession(nextSession);
                    if (nextSession) {
                        const resolvedActor = await fetchActor();
                        if (!cancelled) {
                            setActor(resolvedActor);
                            setError(null);
                        }
                    }
                } else if (event === "SIGNED_OUT") {
                    setSession(null);
                    setActor(null);
                    setError(null);
                }
            },
        );

        return () => {
            cancelled = true;
            listenerData.subscription.unsubscribe();
        };
    }, [fetchActor]);

    const signOut = useCallback(async () => {
        const supabase = getSupabaseClient();
        if (supabase) {
            await supabase.auth.signOut();
        }
        setSession(null);
        setActor(null);
        setError(null);
    }, []);

    return (
        <AuthContext.Provider
            value={{ session, actor, loading, error, signOut, refreshActor }}
        >
            {children}
        </AuthContext.Provider>
    );
}

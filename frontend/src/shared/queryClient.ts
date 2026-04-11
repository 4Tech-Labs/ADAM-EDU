import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/shared/api";

/**
 * Manejador global de errores para queries y mutations.
 *
 * En un 401: el token expiró mientras Supabase auto-refresh estaba en vuelo.
 * - NO llamamos signOut() directamente (causaría dependencia circular con AuthContext).
 * - Cancelamos queries activas y limpiamos el caché; esto detiene todos los
 *   refetchInterval activos (incluido el de summaryQuery cada 30 s).
 * - Si el token está definitivamente muerto, onAuthStateChange(SIGNED_OUT) en
 *   AuthContext hará la limpieza final y redirigirá al login.
 * - Si Supabase refresca el token con éxito, disparará TOKEN_REFRESHED y las
 *   queries se re-habilitarán normalmente.
 */
function handleGlobalError(error: unknown): void {
    if (error instanceof ApiError && error.status === 401) {
        queryClient.cancelQueries();
        queryClient.clear();
    }
}

export const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: handleGlobalError }),
    mutationCache: new MutationCache({ onError: handleGlobalError }),
    defaultOptions: {
        queries: {
            /**
             * staleTime: 30 s — datos considerados frescos durante este período.
             * No se dispara ningún background-refetch si la data tiene menos de 30 s.
             */
            staleTime: 30_000,
            /**
             * gcTime: 5 min — tiempo que una query inactiva (sin suscriptores)
             * permanece en caché antes de ser garbage-collected.
             * (Era "cacheTime" en v4; renombrado a "gcTime" en v5.)
             */
            gcTime: 5 * 60_000,
            /** Refetch silencioso al volver a la pestaña del navegador. */
            refetchOnWindowFocus: true,
            /** Refetch al recuperar conexión de red. */
            refetchOnReconnect: true,
            /**
             * retry personalizado:
             * - 401/403 son errores de autenticación/autorización, no transitorios.
             *   Reintentar solo agotaría cuota y daría falsa esperanza.
             * - Para cualquier otro error, se permite 1 reintento.
             */
            retry: (failureCount, error) => {
                if (
                    error instanceof ApiError &&
                    (error.status === 401 || error.status === 403)
                ) {
                    return false;
                }
                return failureCount < 1;
            },
        },
    },
});

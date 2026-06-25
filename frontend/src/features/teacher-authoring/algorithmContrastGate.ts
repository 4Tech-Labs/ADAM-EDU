import type { StudentProfile } from "@/shared/adam-types";

/**
 * TEMP — El modo "2 algoritmos (baseline + challenger)" (contrast) solo está
 * pedagógicamente completo para clasificación. Hasta abrir bien las demás
 * familias (regresión, clustering), los docentes ml_ds eligen UN algoritmo.
 * Reactivar = poner `mlDsContrastEnabled` en `true` (el backend ya acepta
 * contrast para ml_ds; el catálogo sigue exponiendo challengers). Objeto
 * mutable a propósito: es el único interruptor de reactivación y el seam de
 * test.
 */
export const algorithmFeatureFlags = { mlDsContrastEnabled: false };

/**
 * Whether the contrast (2-algorithm) mode must be hidden for a profile. Only
 * `ml_ds` exposes challengers today, so this is the single gate that turns the
 * whole contrast UI dormant while keeping single-algorithm picking intact.
 */
export function isContrastHiddenForProfile(profile: StudentProfile): boolean {
    return profile === "ml_ds" && !algorithmFeatureFlags.mlDsContrastEnabled;
}

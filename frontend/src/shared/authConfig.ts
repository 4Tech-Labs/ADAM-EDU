/**
 * Microsoft (Azure AD) social login kill-switch.
 *
 * `false` (2026-06-20): el botón "Continuar con Microsoft" se oculta en TODAS las
 * superficies de auth (login/activación de docentes y estudiantes). Los handlers
 * `handleMicrosoftLogin/Activation/Join` y TODO el backend OAuth
 * (university_sso_configs, allowed_auth_methods_for_university,
 * /activate/oauth/complete) quedan intactos.
 *
 * Para retomar Microsoft login: devolver `true` aquí (flip de una línea).
 *
 * Se usa una función (no `const`) a propósito: el tipo de retorno `boolean` evita
 * que TypeScript estreche la rama JSX a `never` (mantiene los handlers OAuth
 * "usados" → sin error de unused-var) y es trivialmente mockeable en tests.
 */
export function isMicrosoftLoginEnabled(): boolean {
    return false;
}

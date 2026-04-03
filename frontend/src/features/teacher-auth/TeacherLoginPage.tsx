/**
 * Teacher login page — placeholder for Issue #6.
 *
 * Issue #6 will implement:
 * - Microsoft OAuth initiation (signInWithOAuth + saveActivationContext for activation flow)
 * - Password-based login for existing accounts
 */
export function TeacherLoginPage() {
    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-24">
            <h1 className="text-xl font-semibold">Acceso docentes</h1>
            <p className="text-sm text-muted-foreground max-w-xs text-center">
                El inicio de sesión completo para docentes estará disponible en la
                próxima versión.
            </p>
        </div>
    );
}

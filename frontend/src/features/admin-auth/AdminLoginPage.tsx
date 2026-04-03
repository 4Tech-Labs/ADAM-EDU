/**
 * Admin login page — placeholder for Issue #8.
 *
 * Issue #8 will implement:
 * - Password-only login form (no self-registration, no OAuth)
 * - Redirect to /admin/change-password when must_rotate_password=true
 * - Redirect to admin dashboard when already authenticated
 */
export function AdminLoginPage() {
    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-24">
            <h1 className="text-xl font-semibold">Portal administrador</h1>
            <p className="text-sm text-muted-foreground max-w-xs text-center">
                El inicio de sesión para administradores estará disponible en la
                próxima versión.
            </p>
        </div>
    );
}

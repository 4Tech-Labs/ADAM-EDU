/**
 * Admin change-password page — placeholder for Issue #8.
 *
 * Protected by RequirePasswordRotation: only reachable when
 * actor.must_rotate_password === true.
 *
 * Issue #8 will implement:
 * - Password change form (POST /api/auth/change-password or Supabase updateUser)
 * - On success: clear must_rotate_password flag + redirect to admin dashboard
 */
export function AdminChangePasswordPage() {
    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-24">
            <h1 className="text-xl font-semibold">Cambiar contraseña</h1>
            <p className="text-sm text-muted-foreground max-w-xs text-center">
                Debes cambiar tu contraseña antes de continuar.
            </p>
        </div>
    );
}

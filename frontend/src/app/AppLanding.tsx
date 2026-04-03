import { Link } from "react-router-dom";

/**
 * Root landing page shown to unauthenticated users.
 * Provides real entry-point links per role — no demo toggles.
 */
export function AppLanding() {
    return (
        <div className="flex flex-col items-center justify-center gap-8 px-4 py-24">
            <h1 className="text-2xl font-semibold tracking-tight">ADAM-EDU</h1>
            <p className="text-sm text-muted-foreground">
                Selecciona tu perfil para continuar
            </p>
            <nav className="flex flex-col gap-3 w-full max-w-xs">
                <Link
                    to="/teacher/login"
                    className="flex items-center justify-center rounded-input bg-adam-accent px-6 py-3 text-sm font-medium text-white hover:opacity-90 transition-opacity"
                >
                    Ingresar como docente
                </Link>
                <Link
                    to="/student/login"
                    className="flex items-center justify-center rounded-input border border-border px-6 py-3 text-sm font-medium hover:bg-muted transition-colors"
                >
                    Ingresar como estudiante
                </Link>
                <Link
                    to="/admin/login"
                    className="flex items-center justify-center rounded-input border border-border px-6 py-3 text-sm font-medium hover:bg-muted transition-colors"
                >
                    Portal administrador
                </Link>
            </nav>
        </div>
    );
}

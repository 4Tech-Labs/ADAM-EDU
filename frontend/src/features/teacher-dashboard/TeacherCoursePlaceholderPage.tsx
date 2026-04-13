import { useNavigate, useParams } from "react-router-dom";

export function TeacherCoursePlaceholderPage() {
    const navigate = useNavigate();
    const { courseId } = useParams<{ courseId: string }>();

    return (
        <div className="min-h-screen bg-[#F0F4F8]">
            <div
                className="w-full"
                style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)" }}
            >
                <div className="mx-auto max-w-6xl px-6 py-10">
                    <p className="text-sm font-semibold uppercase tracking-[0.12em] text-blue-100">
                        Portal Docente
                    </p>
                    <h1 className="mt-2 text-3xl font-bold tracking-tight text-white">
                        Curso en preparación
                    </h1>
                    <p className="mt-3 max-w-2xl text-sm text-blue-100">
                        La vista detallada del curso
                        {courseId ? ` ${courseId}` : ""} todavía no está disponible.
                    </p>
                </div>
            </div>

            <main className="mx-auto max-w-6xl px-6 py-9">
                <section className="rounded-[18px] border border-[#e2e8f0] bg-white p-8 shadow-sm">
                    <h2 className="text-xl font-bold tracking-tight text-slate-900">
                        Esta ruta ya está reservada
                    </h2>
                    <p className="mt-3 max-w-2xl text-sm text-slate-600">
                        El dashboard docente puede navegar de forma segura sin caer en el
                        authoring por error. Cuando se implemente el detalle real del curso,
                        esta pantalla se reemplaza sin romper el enlace existente.
                    </p>
                    <button
                        type="button"
                        onClick={() => navigate("/teacher/dashboard")}
                        className="mt-6 inline-flex items-center justify-center rounded-[11px] bg-[#0144a0] px-5 py-[10px] text-[14px] font-bold text-white"
                    >
                        Volver al dashboard
                    </button>
                </section>
            </main>
        </div>
    );
}

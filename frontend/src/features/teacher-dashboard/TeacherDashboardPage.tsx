import type { ShowToast } from "@/shared/Toast";

import { DashboardHeader } from "./DashboardHeader";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({
    showToast: _showToast,
}: TeacherDashboardPageProps) {
    void _showToast;

    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid="teacher-dashboard-page">
            <DashboardHeader />
            <main className="mx-auto max-w-6xl space-y-10 px-6 py-9">
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10">
                    <p className="text-sm text-slate-500">
                        Teacher Dashboard - WIP
                    </p>
                </div>
            </main>
        </div>
    );
}

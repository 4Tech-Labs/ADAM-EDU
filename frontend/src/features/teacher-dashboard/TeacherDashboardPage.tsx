import type { ShowToast } from "@/shared/Toast";

import { CursosActivosSection } from "./CursosActivosSection";
import { DashboardHeader } from "./DashboardHeader";
import { QuickActionsSection } from "./QuickActionsSection";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({
    showToast,
}: TeacherDashboardPageProps) {
    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid="teacher-dashboard-page">
            <DashboardHeader />
            <main className="mx-auto max-w-6xl space-y-10 px-6 py-9">
                <QuickActionsSection showToast={showToast} />
                <CursosActivosSection />
                <div id="cases-section" aria-hidden="true" className="h-px w-full" />
            </main>
        </div>
    );
}

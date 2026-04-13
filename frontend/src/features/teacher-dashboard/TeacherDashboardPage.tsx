import type { ShowToast } from "@/shared/Toast";
import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";

import { CasosActivosSection } from "./CasosActivosSection";
import { CursosActivosSection } from "./CursosActivosSection";
import { QuickActionsSection } from "./QuickActionsSection";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({
    showToast,
}: TeacherDashboardPageProps) {
    return (
        <TeacherLayout
            testId="teacher-dashboard-page"
            contentClassName="mx-auto max-w-6xl space-y-10 px-6 py-9"
        >
                <QuickActionsSection showToast={showToast} />
                <CursosActivosSection />
                <CasosActivosSection showToast={showToast} />
        </TeacherLayout>
    );
}

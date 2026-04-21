import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";

import { CasosActivosSection } from "./CasosActivosSection";
import { CursosActivosSection } from "./CursosActivosSection";
import { QuickActionsSection } from "./QuickActionsSection";

export function TeacherDashboardPage() {
    return (
        <TeacherLayout
            testId="teacher-dashboard-page"
            contentClassName="mx-auto max-w-6xl space-y-10 px-6 py-9"
        >
                <QuickActionsSection />
                <CursosActivosSection />
                <CasosActivosSection />
        </TeacherLayout>
    );
}

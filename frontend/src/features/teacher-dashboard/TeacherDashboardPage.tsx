import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";
import { PORTAL_CONTENT_SHELL_CLASSNAME } from "@/shared/ui/layout";

import { CasosActivosSection } from "./CasosActivosSection";
import { CursosActivosSection } from "./CursosActivosSection";
import { QuickActionsSection } from "./QuickActionsSection";

export function TeacherDashboardPage() {
    return (
        <TeacherLayout
            testId="teacher-dashboard-page"
            contentClassName={`${PORTAL_CONTENT_SHELL_CLASSNAME} space-y-10 py-9`}
        >
                <QuickActionsSection />
                <CursosActivosSection />
                <CasosActivosSection />
        </TeacherLayout>
    );
}

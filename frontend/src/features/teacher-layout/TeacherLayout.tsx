import type { ReactNode } from "react";

import { PORTAL_CONTENT_SHELL_CLASSNAME } from "@/shared/ui/layout";

import { TeacherUserHeader } from "./TeacherUserHeader";

interface TeacherLayoutProps {
    children: ReactNode;
    contentClassName?: string;
    testId?: string;
}

export function TeacherLayout({
    children,
    contentClassName = `${PORTAL_CONTENT_SHELL_CLASSNAME} py-9`,
    testId,
}: TeacherLayoutProps) {
    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid={testId}>
            <div className="sticky top-0 z-40 shadow-[0_6px_20px_-14px_rgba(1,68,160,0.6)] print:hidden">
                <TeacherUserHeader />
            </div>
            <main className={contentClassName}>{children}</main>
        </div>
    );
}

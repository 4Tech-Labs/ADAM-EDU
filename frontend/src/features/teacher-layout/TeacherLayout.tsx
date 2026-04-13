import type { ReactNode } from "react";

import { TeacherUserHeader } from "./TeacherUserHeader";

interface TeacherLayoutProps {
    children: ReactNode;
    contentClassName?: string;
    testId?: string;
}

export function TeacherLayout({
    children,
    contentClassName = "mx-auto w-full max-w-6xl px-6 py-9",
    testId,
}: TeacherLayoutProps) {
    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid={testId}>
            <div className="sticky top-0 z-40 shadow-[0_6px_20px_-14px_rgba(1,68,160,0.6)]">
                <TeacherUserHeader />
            </div>
            <main className={contentClassName}>{children}</main>
        </div>
    );
}

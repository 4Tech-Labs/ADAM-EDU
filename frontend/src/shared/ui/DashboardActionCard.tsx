import type { ReactNode } from "react";

import { cn } from "@/shared/utils";

interface DashboardActionCardProps {
    title: string;
    subtitle: string;
    subtitleClassName: string;
    gradient: string;
    decorativeBlurLeftClassName: string;
    decorativeBlurRightClassName: string;
    icon: ReactNode;
    onClick: () => void;
    className?: string;
}

export function DashboardActionCard({
    title,
    subtitle,
    subtitleClassName,
    gradient,
    decorativeBlurLeftClassName,
    decorativeBlurRightClassName,
    icon,
    onClick,
    className,
}: DashboardActionCardProps) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                "group relative h-[100px] overflow-hidden rounded-2xl p-5 text-left text-white shadow-lg transition-all duration-200",
                "hover:scale-[1.02] hover:shadow-2xl active:scale-[0.98]",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0144a0]",
                className,
            )}
            style={{ background: gradient, borderRadius: 16 }}
        >
            <div
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-px rounded-t-2xl bg-gradient-to-r from-transparent via-white/50 to-transparent"
            />
            <div
                aria-hidden="true"
                className={cn(
                    "absolute -bottom-5 -right-5 h-24 w-24 rounded-full blur-2xl transition-all duration-500",
                    decorativeBlurRightClassName,
                )}
            />
            <div
                aria-hidden="true"
                className={cn(
                    "absolute -left-4 -top-4 h-16 w-16 rounded-full blur-xl transition-all duration-500",
                    decorativeBlurLeftClassName,
                )}
            />
            <div className="relative z-10 flex items-center justify-between gap-4">
                <div className="min-w-0">
                    <h3 className="text-[16px] font-bold tracking-tight">{title}</h3>
                    <p className={cn("mt-1 text-xs font-medium opacity-80", subtitleClassName)}>
                        {subtitle}
                    </p>
                </div>
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/20 bg-white/20 backdrop-blur-sm transition-colors group-hover:bg-white/30">
                    {icon}
                </div>
            </div>
        </button>
    );
}

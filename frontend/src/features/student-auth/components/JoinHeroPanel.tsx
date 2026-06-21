import { GradCapIcon, LockIcon } from "./icons";

interface JoinHeroPanelProps {
    universityName?: string | null;
    courseTitle?: string | null;
    teacherName?: string | null;
}

/**
 * Left navy/gold "invitation" hero of the /join split card. Shared by the
 * activation and in-place sign-in views. Degrades gracefully when the course
 * title or teacher are unknown (e.g. an invite with a null course_title).
 */
export function JoinHeroPanel({ universityName, courseTitle, teacherName }: JoinHeroPanelProps) {
    const teacherInitial = teacherName?.trim().charAt(0).toUpperCase() ?? "";

    return (
        <div className="relative flex w-full flex-col overflow-hidden p-[36px_28px] text-[#EDE7D6] bg-[linear-gradient(158deg,#0B57B8_0%,#023C88_55%,#04275C_100%)] md:w-auto md:min-w-[320px] md:flex-[1_1_380px] md:p-[48px_46px]">
            {/* Decorative gold rings + glow */}
            <div aria-hidden className="pointer-events-none absolute -right-[90px] -top-[90px] h-[280px] w-[280px] rounded-full border border-[rgba(216,184,115,0.22)]" />
            <div aria-hidden className="pointer-events-none absolute -right-[50px] -top-[50px] h-[180px] w-[180px] rounded-full border border-[rgba(216,184,115,0.14)]" />
            <div aria-hidden className="pointer-events-none absolute -bottom-[120px] -left-[80px] h-[300px] w-[300px] rounded-full bg-[radial-gradient(circle,rgba(216,184,115,0.08)_0%,rgba(216,184,115,0)_70%)]" />

            <div className="relative flex flex-1 flex-col md:min-h-[440px]">
                <div className="flex items-center gap-3">
                    <div className="flex h-[42px] w-[42px] items-center justify-center rounded-[12px] border border-[rgba(216,184,115,0.3)] bg-[rgba(216,184,115,0.14)]">
                        <GradCapIcon />
                    </div>
                    {universityName && (
                        <div className="text-[14px] font-semibold tracking-[0.2px] text-[#F1ECDD]">
                            {universityName}
                        </div>
                    )}
                </div>

                <div className="my-auto">
                    <div className="mb-[14px] text-[11px] font-bold uppercase tracking-[2.4px] text-[#D8B873]">
                        Invitación al curso
                    </div>
                    <h2 className="mb-[26px] font-['Source_Serif_4'] text-[30px] font-medium leading-[1.18] tracking-[-0.4px] text-[#FBF8F0]">
                        {courseTitle ?? "Te damos la bienvenida a tu curso"}
                    </h2>

                    {teacherName && (
                        <div className="flex items-center gap-[13px] rounded-[14px] border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.05)] p-[14px_16px]">
                            <div className="flex h-[42px] w-[42px] flex-none items-center justify-center rounded-full bg-[linear-gradient(145deg,#D8B873,#B68F46)] font-['Source_Serif_4'] text-[18px] font-semibold text-[#04275C]">
                                {teacherInitial}
                            </div>
                            <div>
                                <div className="mb-0.5 text-[11.5px] tracking-[0.3px] text-[#A9C2B5]">
                                    Impartido por
                                </div>
                                <div className="text-[15px] font-semibold text-[#F1ECDD]">{teacherName}</div>
                            </div>
                        </div>
                    )}
                </div>

                <div className="flex items-center gap-2 text-[12.5px] text-[rgba(237,231,214,0.72)]">
                    <LockIcon className="text-[rgba(216,184,115,0.9)]" />
                    Acceso inmediato y seguro a tu invitación
                </div>
            </div>
        </div>
    );
}

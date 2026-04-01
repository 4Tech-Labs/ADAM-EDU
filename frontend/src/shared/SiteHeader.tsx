/** ADAM — Sticky site header, always visible */

export function SiteHeader() {
    return (
        <header className="sticky top-0 z-50 flex h-[58px] items-center justify-between bg-[#0144a0] px-5 shadow-md">
            {/* Logo */}
            <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-white">
                    <span className="font-sans text-[1.0625rem] font-bold tracking-tight text-[#0144a0]">A</span>
                </div>
                <span className="type-body font-semibold text-white tracking-[-0.01em]">
                    ADAM <span className="text-white/80 font-medium">Edu</span>
                </span>
            </div>

            {/* Right label */}
            <span className="type-overline text-white/70">
                Portal Profesor
            </span>
        </header>
    );
}

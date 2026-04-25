import { useEffect, useRef } from "react";

export interface SectionRailItem {
    id: string;
    label: string;
    level: number;
}

export function SectionRail({
    sections,
    activeSection,
    onSectionSelect,
}: {
    sections: SectionRailItem[];
    activeSection: string;
    onSectionSelect: (id: string) => void;
}) {
    const railRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const rail = railRef.current;
        if (!rail) {
            return;
        }

        const activeIndex = sections.findIndex((section) => section.id === activeSection);
        if (activeIndex < 0) {
            return;
        }

        const childIndex = activeIndex === 0 ? 0 : activeIndex * 2;
        const activeElement = rail.children[childIndex] as HTMLElement | undefined;
        if (!activeElement) {
            return;
        }

        const elementTop = activeElement.offsetTop;
        const elementHeight = activeElement.offsetHeight;
        const railHeight = rail.clientHeight;
        const railScroll = rail.scrollTop;

        if (elementTop < railScroll) {
            rail.scrollTop = elementTop;
        } else if (elementTop + elementHeight > railScroll + railHeight) {
            rail.scrollTop = elementTop + elementHeight - railHeight;
        }
    }, [activeSection, sections]);

    return (
        <>
            <p className="text-[12px] font-bold text-slate-400 uppercase tracking-widest mb-4 px-1">
                En esta sección
            </p>
            <div ref={railRef} className="flex-1 overflow-y-auto custom-scroll flex flex-col">
                {sections.map((section, index) => {
                    const isActiveSection = activeSection === section.id;
                    const isVisited = sections.findIndex((item) => item.id === activeSection) > index;

                    return (
                        <div key={section.id}>
                            {index > 0 && <div className={`rail-conn${isVisited ? " on" : ""}`} />}
                            <div
                                className={`rail-item${isActiveSection ? " active" : isVisited ? " visited" : ""}`}
                                onClick={() => onSectionSelect(section.id)}
                            >
                                <div className="rail-dot">{index + 1}</div>
                                <span className="rail-label" style={{ paddingLeft: section.level === 3 ? "4px" : "0" }}>
                                    {section.label}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </>
    );
}
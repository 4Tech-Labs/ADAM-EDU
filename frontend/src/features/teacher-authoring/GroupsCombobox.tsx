import { useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { cn } from "@/shared/utils";
import type { TeacherCourseItem } from "@/shared/adam-types";

interface GroupsComboboxProps {
    courses: TeacherCourseItem[];
    value: string[];
    onAdd: (courseId: string) => void;
    onRemove: (courseId: string) => void;
    hasError?: boolean;
}

function courseLabel(course: TeacherCourseItem): string {
    return course.code ? `${course.title} (${course.code})` : course.title;
}

export function GroupsCombobox({ courses, value, onAdd, onRemove, hasError }: GroupsComboboxProps) {
    const [open, setOpen] = useState(false);
    const [filter, setFilter] = useState("");

    const filterLower = filter.toLowerCase();
    const selected = courses.filter((c) => value.includes(c.id));
    const available = courses.filter(
        (c) =>
            !value.includes(c.id) &&
            (!filter || courseLabel(c).toLowerCase().includes(filterLower)),
    );

    const triggerLabel =
        value.length === 0
            ? "Seleccione grupos..."
            : `${value.length} grupo${value.length !== 1 ? "s" : ""} seleccionado${value.length !== 1 ? "s" : ""}`;

    const handleOpenChange = (next: boolean) => {
        setOpen(next);
        if (!next) setFilter("");
    };

    return (
        <div>
            <Popover open={open} onOpenChange={handleOpenChange}>
                <PopoverTrigger asChild>
                    <button
                        id="field-grupos"
                        type="button"
                        aria-expanded={open}
                        className={cn(
                            "input-base w-full flex items-center justify-between rounded-lg border bg-white px-3.5 py-2.5 text-sm text-left transition hover:border-[#0144a0]",
                            hasError ? "border-red-500 input-error" : "border-slate-200"
                        )}
                    >
                        <span className={value.length === 0 ? "text-slate-400" : "text-slate-800"}>
                            {triggerLabel}
                        </span>
                        <ChevronDownIcon className="size-4 opacity-50 flex-shrink-0" />
                    </button>
                </PopoverTrigger>
                <PopoverContent
                    align="start"
                    sideOffset={4}
                    className="p-0 w-[var(--radix-popover-trigger-width)]"
                >
                    <div className="border-b border-slate-100 px-2 py-1.5">
                        <input
                            aria-label="Buscar grupo"
                            type="text"
                            value={filter}
                            onChange={(e) => setFilter(e.target.value)}
                            placeholder="Buscar curso..."
                            className="w-full bg-transparent px-1.5 py-1 text-sm text-slate-800 outline-none placeholder:text-slate-400"
                            autoFocus
                        />
                    </div>
                    <div className="max-h-48 overflow-y-auto py-1">
                        {courses.length === 0 ? (
                            <div className="px-3 py-4 text-sm text-slate-400 text-center">
                                No tienes cursos disponibles
                            </div>
                        ) : (
                            <>
                                {selected.map((c) => {
                                    const label = courseLabel(c);
                                    return (
                                        <button
                                            key={c.id}
                                            type="button"
                                            onClick={() => onRemove(c.id)}
                                            className="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 text-left"
                                        >
                                            <span className="flex items-center gap-2">
                                                <span aria-hidden="true" className="text-[#0144a0] text-xs font-bold">✓</span>
                                                {label}
                                            </span>
                                            <span aria-hidden="true" className="text-slate-400 text-base leading-none">×</span>
                                        </button>
                                    );
                                })}
                                {available.length === 0 && filter ? (
                                    <div className="px-3 py-2 text-sm text-slate-400 text-center">
                                        Sin resultados
                                    </div>
                                ) : null}
                                {available.map((c) => {
                                    const label = courseLabel(c);
                                    return (
                                        <button
                                            key={c.id}
                                            type="button"
                                            onClick={() => {
                                                onAdd(c.id);
                                                setOpen(false);
                                            }}
                                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-blue-50 text-left"
                                        >
                                            <span aria-hidden="true" className="w-3 inline-block" />
                                            {label}
                                        </button>
                                    );
                                })}
                            </>
                        )}
                    </div>
                </PopoverContent>
            </Popover>
            {value.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                    {value.map((courseId) => {
                        const course = courses.find((item) => item.id === courseId);
                        const label = course ? courseLabel(course) : courseId;
                        return (
                        <button
                            key={courseId}
                            type="button"
                            onClick={() => onRemove(courseId)}
                            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:border-[#0144a0] hover:text-[#0144a0]"
                        >
                            <span>{label}</span>
                            <span aria-hidden="true" className="text-base leading-none">×</span>
                        </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}


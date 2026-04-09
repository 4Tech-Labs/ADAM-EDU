/** ADAM — Toast notification system with useToast hook */

import { useCallback, useState } from "react";

export type ToastType = "success" | "error" | "default";
export type ShowToast = (message: string, type?: ToastType) => void;

interface ToastItem {
    id: number;
    message: string;
    type: ToastType;
}

let nextId = 0;

export function useToast() {
    const [toasts, setToasts] = useState<ToastItem[]>([]);

    const showToast = useCallback<ShowToast>((message, type = "default") => {
        const id = nextId++;
        setToasts((prev) => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
        }, 2800);
    }, []);

    const ToastContainer = useCallback(
        () => (
            <div className="fixed bottom-4 right-4 z-[300] flex flex-col gap-2">
                {toasts.map((t) => (
                    <div
                        key={t.id}
                        role="status"
                        aria-live="polite"
                        className={`animate-toast-in rounded-input px-4 py-2.5 text-sm font-medium text-white shadow-lg ${t.type === "success"
                                ? "bg-adam-accent"
                                : t.type === "error"
                                    ? "bg-danger"
                                    : "bg-ink"
                            }`}
                    >
                        {t.message}
                    </div>
                ))}
            </div>
        ),
        [toasts]
    );

    return { showToast, ToastContainer } as const;
}

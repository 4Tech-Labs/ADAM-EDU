import { useCallback, useEffect, useRef, useState } from "react";

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
    const timeoutIdsRef = useRef<number[]>([]);

    useEffect(() => {
        return () => {
            timeoutIdsRef.current.forEach((timeoutId) => {
                window.clearTimeout(timeoutId);
            });
            timeoutIdsRef.current = [];
        };
    }, []);

    const showToast = useCallback<ShowToast>((message, type = "default") => {
        const id = nextId++;
        setToasts((prev) => [...prev, { id, message, type }]);

        const timeoutId = window.setTimeout(() => {
            setToasts((prev) => prev.filter((toast) => toast.id !== id));
            timeoutIdsRef.current = timeoutIdsRef.current.filter(
                (activeTimeoutId) => activeTimeoutId !== timeoutId,
            );
        }, 2800);

        timeoutIdsRef.current.push(timeoutId);
    }, []);

    const ToastContainer = useCallback(
        () => (
            <div className="fixed bottom-4 right-4 z-[300] flex flex-col gap-2">
                {toasts.map((toast) => (
                    <div
                        key={toast.id}
                        role="status"
                        aria-live="polite"
                        className={`animate-toast-in rounded-input px-4 py-2.5 text-sm font-medium text-white shadow-lg ${
                            toast.type === "success"
                                ? "bg-adam-accent"
                                : toast.type === "error"
                                  ? "bg-danger"
                                  : "bg-ink"
                        }`}
                    >
                        {toast.message}
                    </div>
                ))}
            </div>
        ),
        [toasts],
    );

    return { showToast, ToastContainer } as const;
}

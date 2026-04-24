import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import type { ReactNode } from "react";
import { ToastContext, type ToastType } from "@/shared/toast-context";

interface ToastItem {
    id: number;
    message: string;
    type: ToastType;
}

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<ToastItem[]>([]);
    const timeoutIdsRef = useRef<number[]>([]);
    const nextIdRef = useRef(0);

    useEffect(() => {
        return () => {
            timeoutIdsRef.current.forEach((timeoutId) => {
                window.clearTimeout(timeoutId);
            });
            timeoutIdsRef.current = [];
        };
    }, []);

    const showToast = useCallback((message: string, type: ToastType = "info") => {
        const id = nextIdRef.current++;
        setToasts((prev) => [...prev, { id, message, type }]);

        const timeoutId = window.setTimeout(() => {
            setToasts((prev) => prev.filter((toast) => toast.id !== id));
            timeoutIdsRef.current = timeoutIdsRef.current.filter(
                (activeTimeoutId) => activeTimeoutId !== timeoutId,
            );
        }, 4000);

        timeoutIdsRef.current.push(timeoutId);
    }, []);

    const value = useMemo(() => ({ showToast }), [showToast]);

    return (
        <ToastContext.Provider value={value}>
            {children}
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
        </ToastContext.Provider>
    );
}

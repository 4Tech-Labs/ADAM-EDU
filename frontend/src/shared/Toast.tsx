import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import type { ReactNode } from "react";

export type ToastType = "success" | "error" | "info";

interface ToastItem {
    id: number;
    message: string;
    type: ToastType;
}

interface ToastContextValue {
    showToast: (message: string, type?: ToastType) => void;
}

let nextId = 0;

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
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

    const showToast = useCallback((message: string, type: ToastType = "info") => {
        const id = nextId++;
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

export function useToast(): ToastContextValue {
    const ctx = useContext(ToastContext);
    if (!ctx) {
        throw new Error("useToast must be used inside ToastProvider");
    }
    return ctx;
}

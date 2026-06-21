import { useId, useState } from "react";

import { FIELD_INPUT_CLASS, FIELD_LABEL_CLASS } from "./fieldStyles";
import { AlertCircleIcon } from "./icons";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

interface PasswordFieldProps {
    id: string;
    name: string;
    label: string;
    value: string;
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
    onBlur?: (event: React.FocusEvent<HTMLInputElement>) => void;
    placeholder?: string;
    autoComplete: "new-password" | "current-password";
    /** Show the strength meter (only meaningful while creating a password). */
    showMeter?: boolean;
    error?: string | null;
    required?: boolean;
}

/**
 * Password input with an inline show/hide toggle and an optional strength meter.
 *
 * Contract relied on by StudentJoinPage.test.tsx: the toggle is a `type="button"`
 * (never counted by `querySelectorAll('input[type=password]')`) and the input
 * defaults to `type="password"` (hidden), so the activate/sign-in password counts
 * stay 2 / 1.
 */
export function PasswordField({
    id,
    name,
    label,
    value,
    onChange,
    onBlur,
    placeholder,
    autoComplete,
    showMeter = false,
    error,
    required,
}: PasswordFieldProps) {
    const [show, setShow] = useState(false);
    const errorId = useId();

    return (
        <div>
            <div className="mb-2 flex items-center justify-between">
                <label htmlFor={id} className={FIELD_LABEL_CLASS}>
                    {label} <span className="text-[#0144a0]">*</span>
                </label>
                <button
                    type="button"
                    onClick={() => setShow((prev) => !prev)}
                    aria-pressed={show}
                    aria-label={show ? "Ocultar contraseña" : "Mostrar contraseña"}
                    className="cursor-pointer rounded-[4px] border-none bg-transparent p-0 text-[12.5px] font-semibold text-[#0144a0] hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0144a0]"
                >
                    {show ? "Ocultar" : "Mostrar"}
                </button>
            </div>
            <input
                id={id}
                name={name}
                type={show ? "text" : "password"}
                value={value}
                onChange={onChange}
                onBlur={onBlur}
                placeholder={placeholder}
                autoComplete={autoComplete}
                required={required}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                className={FIELD_INPUT_CLASS}
            />
            {showMeter && <PasswordStrengthMeter password={value} />}
            {error && (
                <p
                    id={errorId}
                    role="alert"
                    className="mt-[7px] flex items-center gap-[5px] text-[12.5px] text-[#C2462E]"
                >
                    <AlertCircleIcon />
                    {error}
                </p>
            )}
        </div>
    );
}

import { useContext } from "react";
import type { AuthContextValue } from "./auth-types";
import { AuthContext } from "./auth-context";

export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext);
    if (ctx === undefined) {
        throw new Error("useAuth must be used inside <AuthProvider>");
    }
    return ctx;
}

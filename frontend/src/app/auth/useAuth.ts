import { useContext } from "react";
import { AuthContext } from "./AuthContext";
import type { AuthContextValue } from "./auth-types";

export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext);
    if (ctx === undefined) {
        throw new Error("useAuth must be used inside <AuthProvider>");
    }
    return ctx;
}

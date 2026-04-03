/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_SUPABASE_URL: string;
    readonly VITE_SUPABASE_ANON_KEY: string;
    readonly VITE_AUTH_CALLBACK_URL: string;
    readonly VITE_APP_BASE_URL: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}

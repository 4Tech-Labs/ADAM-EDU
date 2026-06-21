// Shared field styling for the /join invitation form. Centralised so the email/name
// inputs in StudentJoinPage and the PasswordField stay byte-identical (no drift).

export const FIELD_INPUT_CLASS =
    "w-full rounded-[13px] border-[1.5px] border-[#DEE3EC] bg-[#F6F8FB] px-[15px] py-[13px] " +
    "text-[15px] text-[#16181D] outline-none transition-[border-color,box-shadow] " +
    "placeholder:text-[#9AA3B2] focus-visible:border-[#0144a0] focus-visible:bg-white " +
    "focus-visible:shadow-[0_0_0_4px_rgba(1,68,160,0.14)] aria-[invalid=true]:border-[#C2462E]";

export const FIELD_LABEL_CLASS =
    "flex items-center gap-[5px] text-[13px] font-semibold text-[#2B3340]";

// Inline text-link buttons ("Inicia sesión" / "Crear cuenta") used to toggle auth modes.
export const TOGGLE_LINK_CLASS =
    "cursor-pointer rounded-[4px] border-none bg-transparent p-0 font-bold text-[#0144a0] " +
    "hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0144a0]";

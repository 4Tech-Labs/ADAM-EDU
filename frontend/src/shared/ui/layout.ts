export const PORTAL_HEADER_HEIGHT_PX = 80;
export const PORTAL_HEADER_HEIGHT_CLASSNAME = "h-20";
export const PORTAL_SHELL_HEIGHT_DVH = `calc(100dvh - ${PORTAL_HEADER_HEIGHT_PX}px)`;
export const PORTAL_SHELL_HEIGHT_VH_CLASSNAME = "h-[calc(100vh-80px)]";

// Safety cap that only engages on ultra-wide monitors; on normal monitors
// (<=2400px) the portal content is effectively full-bleed.
export const PORTAL_MAX_WIDTH_CLASSNAME = "max-w-[2400px]";
// Responsive horizontal gutter shared by topbar rows and content, so their
// left/right edges stay aligned at every width.
export const PORTAL_GUTTER_X_CLASSNAME = "px-4 sm:px-6 lg:px-8";
// Horizontal shell applied to each portal's <main> and to the inner row of its
// topbar. Written as a full string literal (not interpolated) so the Tailwind
// v4 source scanner generates every class.
export const PORTAL_CONTENT_SHELL_CLASSNAME =
    "mx-auto w-full max-w-[2400px] px-4 sm:px-6 lg:px-8";
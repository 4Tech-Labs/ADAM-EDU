export async function copyToClipboard(value: string): Promise<boolean> {
    if (!navigator.clipboard?.writeText) {
        return false;
    }

    try {
        await navigator.clipboard.writeText(value);
        return true;
    } catch {
        return false;
    }
}
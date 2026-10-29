
export const SERVER_UNREACHABLE_KEY = 'error.server_unreachable';

/* could not be reached */
export function reasonOf(error, t) {
    if (typeof error === 'string') {
        const text = error.trim();
        if (text) return text;
    } else if (error && typeof error === 'object' && 'message' in error) {
        const message = String(error.message || '').trim();
        if (message) return message;
    }
    return t(SERVER_UNREACHABLE_KEY);
}

import { ApiError } from '../../../opscenter/api/auth.svelte';

export function errorText(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = (error.payload as { detail?: unknown } | null)?.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return detail.map(String).join('; ');
        if (detail && typeof detail === 'object' && typeof (detail as { detail?: unknown }).detail === 'string') {
            return (detail as { detail: string }).detail;
        }
        return error.message;
    }
    return error instanceof Error ? error.message : String(error);
}

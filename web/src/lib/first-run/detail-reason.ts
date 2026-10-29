
export function detailReasonOf(body: unknown): string {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const reason = (detail as { reason?: unknown } | null)?.reason;
    return typeof reason === 'string' ? reason : '';
}

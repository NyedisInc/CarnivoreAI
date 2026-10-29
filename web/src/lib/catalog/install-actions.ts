
export type InstallState =
    | { kind: 'idle' }
    | { kind: 'verifying' }
    | { kind: 'refused'; code: string }
    | { kind: 'installing' }
    | { kind: 'installed' }
    | { kind: 'update-available' };

export type InstallEvent =
    | { kind: 'verify' }
    | { kind: 'install' }
    | { kind: 'installed' }
    | { kind: 'refused'; code: string }
    | { kind: 'update_found' }
    | { kind: 'dismiss' }
    | { kind: 'uninstalled' };

export const IDLE: InstallState = { kind: 'idle' };

export function isBusy(state: InstallState): boolean {
    return state.kind === 'verifying' || state.kind === 'installing';
}

export function transition(state: InstallState, event: InstallEvent): InstallState {
    if (event.kind === 'refused') {
        return { kind: 'refused', code: event.code };
    }

    if (state.kind === 'refused') {
        if (event.kind === 'verify') return { kind: 'verifying' };
        if (event.kind === 'dismiss') return IDLE;
        return state;
    }

    switch (event.kind) {
        case 'verify':
            return isBusy(state) ? state : { kind: 'verifying' };
        case 'install':
            return state.kind === 'verifying' ? { kind: 'installing' } : state;
        case 'installed':
            return state.kind === 'installing' ? { kind: 'installed' } : state;
        case 'update_found':
            return state.kind === 'installed' ? { kind: 'update-available' } : state;
        case 'uninstalled':
            return state.kind === 'installed' || state.kind === 'update-available'
                ? IDLE
                : state;
        case 'dismiss':
            return state;
        default:
            return state;
    }
}

/* its own sentence */
export function refusalCodeOf(error: unknown): string | null {
    if (!error || typeof error !== 'object') return null;
    const err = error as { body?: unknown; detail?: unknown };
    const fromBody = (err.body as { code?: unknown } | null | undefined)?.code;
    if (typeof fromBody === 'string' && fromBody.trim()) return fromBody.trim();
    const detail = err.detail;
    if (detail && typeof detail === 'object') {
        const fromDetail = (detail as { code?: unknown }).code;
        if (typeof fromDetail === 'string' && fromDetail.trim()) return fromDetail.trim();
    }
    return null;
}

/* the api client */
export function refusalPayloadOf(error: unknown): Record<string, unknown> | null {
    if (!error || typeof error !== 'object') return null;
    const err = error as { body?: unknown; detail?: unknown };
    const isObject = (v: unknown): v is Record<string, unknown> =>
        !!v && typeof v === 'object' && !Array.isArray(v);
    const body = err.body;
    if (isObject(body)) return isObject(body.detail) ? body.detail : body;
    return isObject(err.detail) ? err.detail : null;
}

export function seededState(
    current: InstallState,
    updateAvailable: boolean | null | undefined,
    installed: boolean,
): InstallState {
    if (current.kind === 'refused' || isBusy(current)) return current;
    if (!installed) return IDLE;
    return installedState(updateAvailable);
}

export function installedState(updateAvailable: boolean | null | undefined): InstallState {
    return updateAvailable === true ? { kind: 'update-available' } : { kind: 'installed' };
}

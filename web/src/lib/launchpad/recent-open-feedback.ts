/* could not */
import type { Translate } from './recent';

export const OPEN_TOAST_KIND = 'RecentOpen';

export type OpenStep = 'opening' | 'opened' | 'failed';

interface ToastSurface {
    add(toast: Record<string, unknown>): void;
}

export interface OpenedSession {
    id: string;
    tmuxName: string;
}

export function openToast(
    step: OpenStep,
    name: string,
    reason: string,
    t: Translate,
    now: number = Date.now(),
): Record<string, unknown> {
    return {
        id: `recent-open:${step}:${name}:${now}`,
        session_id: null,
        kind: OPEN_TOAST_KIND,
        title: t(`session.restart.toast.${step}.title`),
        body: t(`session.restart.toast.${step}.body`, { name, reason }),
        session_label: t('session.restart.toast.surface'),
        local: true,
    };
}

export function raiseToast(toast: Record<string, unknown>): boolean {
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    if (!surface || typeof surface.add !== 'function') return false;
    surface.add(toast);
    return true;
}

export function openedSession(result: unknown): OpenedSession | null {
    if (!result || typeof result !== 'object') return null;
    const body = result as { session?: unknown };
    const s = (body.session && typeof body.session === 'object' ? body.session : result) as {
        id?: unknown;
        tmux_session?: unknown;
    };
    const id = typeof s.id === 'string' ? s.id : '';
    const tmuxName = typeof s.tmux_session === 'string' ? s.tmux_session : '';
    return id || tmuxName ? { id, tmuxName } : null;
}

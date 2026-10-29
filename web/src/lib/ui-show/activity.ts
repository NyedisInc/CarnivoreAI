import { accessToken, authFetch } from '../../opscenter/api/auth.svelte';
import { thisTabId } from '../../opscenter/api/size-master.svelte';

export const ACTIVITY_THROTTLE_MS = 3000;

export const ACTIVITY_EVENTS = ['pointerdown', 'keydown'] as const;

export interface ActivityDeps {
    clientId: () => string | null;
    post: (clientId: string) => Promise<unknown>;
    now: () => number;
}

export function browserActivityDeps(): ActivityDeps {
    return {
        clientId: thisTabId,
        post: (clientId) => authFetch('/ui/activity', { method: 'POST', body: JSON.stringify({ client_id: clientId }) }),
        now: () => Date.now(),
    };
}

function soloWindow(): boolean {
    return typeof document !== 'undefined' && document.documentElement.hasAttribute('data-solo');
}

export function startActivityReport(
    target: Window | null = typeof window !== 'undefined' ? window : null,
    deps: ActivityDeps = browserActivityDeps(),
): () => void {
    if (!target || soloWindow()) return () => {};
    let lastSent = Number.NEGATIVE_INFINITY;
    const onInput = (): void => {
        const at = deps.now();
        if (at - lastSent < ACTIVITY_THROTTLE_MS) return;
        const id = deps.clientId();
        if (!id) return;
        lastSent = at;
        deps.post(id).catch((err: unknown) => {
            console.debug('ui show: activity report failed', err);
        });
    };
    for (const name of ACTIVITY_EVENTS) target.addEventListener(name, onInput, { capture: true, passive: true });
    // restored from
    const onShow = (): void => {
        if (typeof document !== 'undefined' && document.hasFocus()) onInput();
    };
    target.addEventListener('pageshow', onShow);
    onShow();
    return () => {
        for (const name of ACTIVITY_EVENTS) target.removeEventListener(name, onInput, { capture: true });
        target.removeEventListener('pageshow', onShow);
    };
}

export interface GoneDeps {
    clientId: () => string | null;
    post: (clientId: string) => Promise<unknown> | void;
}

export function browserGoneDeps(): GoneDeps {
    return {
        clientId: thisTabId,
        post: (clientId) => {
            const token = accessToken();
            if (!token) return;
            return fetch('/api/v1/ui/activity/gone', {
                method: 'POST',
                keepalive: true,
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                body: JSON.stringify({ client_id: clientId }),
            });
        },
    };
}

export function startGoneReport(
    target: Window | null = typeof window !== 'undefined' ? window : null,
    deps: GoneDeps = browserGoneDeps(),
): () => void {
    if (!target || soloWindow()) return () => {};
    const onHide = (event?: Event): void => {
        if ((event as PageTransitionEvent | undefined)?.persisted) return;
        const id = deps.clientId();
        if (!id) return;
        try {
            Promise.resolve(deps.post(id)).catch((err: unknown) => console.debug('ui show: gone report failed', err));
        } catch (err) {
            console.debug('ui show: gone report failed', err);
        }
    };
    target.addEventListener('pagehide', onHide);
    return () => target.removeEventListener('pagehide', onHide);
}

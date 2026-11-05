import { authFetch } from '../../opscenter/api/auth.svelte';
import { WATCHED_EVENT, watchedSessionId } from './quiet-watched.svelte';

export const BEAT_MS = 30000;
export const IDLE_MS = 5 * 60 * 1000;

const INPUT_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'pointermove'] as const;

export interface PresenceDeps {
    clientId?: () => string | null;
    post?: (clientId: string, active: boolean, watched: string) => void;
    watched?: () => string;
    now?: () => number;
    doc?: Document;
    win?: Window;
}

function pageClientId(): string | null {
    const master = (globalThis as unknown as { TerminalSizeMaster?: { clientId?: () => string } }).TerminalSizeMaster;
    try {
        return typeof master?.clientId === 'function' ? master.clientId() : null;
    } catch {
        return null;
    }
}

function postBeat(clientId: string, active: boolean, watched: string): void {
    void authFetch('/notifications/presence', { method: 'POST', body: JSON.stringify({ client_id: clientId, active, watched }), keepalive: true }).catch(() => undefined);
}

export function startPresenceBeacon(deps: PresenceDeps = {}): () => void {
    const doc = deps.doc ?? document;
    const win = deps.win ?? window;
    const now = deps.now ?? Date.now;
    const idOf = deps.clientId ?? pageClientId;
    const post = deps.post ?? postBeat;
    const watched = deps.watched ?? watchedSessionId;
    let lastInput = Number.NEGATIVE_INFINITY;
    let announced = false;

    const present = (): boolean => doc.visibilityState === 'visible' && now() - lastInput < IDLE_MS;

    const beat = (): void => {
        const id = idOf();
        if (!id) return;
        if (present()) {
            announced = true;
            post(id, true, watched());
        } else if (announced) {
            announced = false;
            post(id, false, '');
        }
    };

    const onInput = (): void => {
        const first = !present();
        lastInput = now();
        if (first) beat();
    };
    const onVisibility = (): void => beat();
    const onHide = (): void => {
        const id = idOf();
        if (id && announced) {
            announced = false;
            post(id, false, '');
        }
    };

    for (const name of INPUT_EVENTS) doc.addEventListener(name, onInput, { passive: true });
    doc.addEventListener('visibilitychange', onVisibility);
    win.addEventListener('pagehide', onHide);
    win.addEventListener(WATCHED_EVENT, onVisibility);
    const timer = win.setInterval(beat, BEAT_MS);
    return () => {
        for (const name of INPUT_EVENTS) doc.removeEventListener(name, onInput);
        doc.removeEventListener('visibilitychange', onVisibility);
        win.removeEventListener('pagehide', onHide);
        win.removeEventListener(WATCHED_EVENT, onVisibility);
        win.clearInterval(timer);
    };
}

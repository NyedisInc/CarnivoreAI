import { goTo, type NavTarget } from '../nav-items/nav-items';

export const NOTIFY_CLICK_MESSAGE = 'carnivore.notify-click';

const ID = /^[A-Za-z0-9_:.-]{0,200}$/;

export function targetOf(data: unknown): NavTarget | null {
    const d = data as { type?: unknown; session_id?: unknown; tmux_name?: unknown } | null;
    if (!d || typeof d !== 'object' || d.type !== NOTIFY_CLICK_MESSAGE) return null;
    const id = typeof d.session_id === 'string' && ID.test(d.session_id) ? d.session_id : '';
    const tmuxName = typeof d.tmux_name === 'string' && ID.test(d.tmux_name) ? d.tmux_name : '';
    return id || tmuxName ? { kind: 'session', id, tmuxName } : null;
}

let installed = false;

export function installDesktopClick(go: (target: NavTarget) => Promise<boolean> = goTo): void {
    if (installed) return;
    installed = true;
    window.addEventListener('message', (event: MessageEvent) => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        const target = targetOf(event.data);
        if (target) void go(target);
    });
}

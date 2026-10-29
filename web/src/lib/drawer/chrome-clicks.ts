import { clickEnv } from './click-env';
import { toggleCollapsed } from './store';

const LAYOUT_FOLD_PREFIX = 'layout:';

interface Repaintable { repaint?: () => void }

type ClosestTarget = { closest?(selector: string): Element | null };

export function shellOwns(target: EventTarget | null): boolean {
    const shell = clickEnv().CloudeWeb?.sidebarShell;
    return !!(shell && typeof shell.owns === 'function' && shell.owns(target));
}

export function onGroupToggleClick(ctrl: Repaintable, btnEl: Element): void {
    const key = btnEl.getAttribute('data-group-toggle');
    if (!key) return;
    const nowPresent = toggleCollapsed(key);
    ctrl.repaint?.();
    const region = document.getElementById('session-sidebar-live');
    if (!region) return;
    const isLayoutItem = key.indexOf(LAYOUT_FOLD_PREFIX) === 0;
    const word = isLayoutItem ? (nowPresent ? 'expanded' : 'collapsed') : (nowPresent ? 'collapsed' : 'expanded');
    region.textContent = `${key} group ${word}`;
}

export function claim(ctrl: Repaintable, e: Event): boolean {
    const target = e.target as ClosestTarget | null;
    const at = (sel: string): Element | null => (target && target.closest ? target.closest(sel) : null);
    if (shellOwns(e.target)) return true;
    if (at('.session-sidebar-rename-edit')) {
        e.stopPropagation();
        return true;
    }
    const groupToggle = at('[data-group-toggle]');
    if (groupToggle) {
        e.stopPropagation();
        onGroupToggleClick(ctrl, groupToggle);
        return true;
    }
    return false;
}

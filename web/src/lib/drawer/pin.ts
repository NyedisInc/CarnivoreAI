import { drawerEnv } from './env';


export const MOBILE_MAX_PX = 700;
export const BODY_CLASS = 'session-sidebar-pinned';
export const RAIL_CLASS = 'session-sidebar-railed';
export const RAIL_MIN_PX = 1024;

export interface DockableDrawer {
    isOpen: boolean;
    toggleBtn: HTMLElement | null;
    backdrop: HTMLElement | null;
    _transientOpen: boolean;
    close(opts?: { persist?: boolean }): void;
}


let lastEffective: string | null = null;
let watching = false;

function drawerNow(): DockableDrawer | null {
    const d = (drawerEnv() as { SessionSidebar?: DockableDrawer }).SessionSidebar;
    return d && typeof d === 'object' ? d : null;
}

export function isMobile(): boolean {
    const width = window.innerWidth;
    if (!width) return false;
    return width <= MOBILE_MAX_PX;
}

export function opensFrom(stored: string | null): boolean {
    if (stored === '0') return false;
    if (stored === '1') return true;
    return !isMobile();
}

export function isEffectivelyPinned(): boolean {
    return !isMobile();
}

export function apply(): void {
    const sidebar = drawerNow();
    const effective = isEffectivelyPinned();
    const docked = effective && !!sidebar && sidebar.isOpen;
    document.body.classList.toggle(BODY_CLASS, docked);
    const width = window.innerWidth;
    const railed = !!sidebar && !sidebar.isOpen && !!sidebar.toggleBtn
        && !sidebar.toggleBtn.classList.contains('hidden') && (!width || width >= RAIL_MIN_PX);
    document.body.classList.toggle(RAIL_CLASS, railed);
    const layout = (docked ? 'docked' : '') + (railed ? 'railed' : '');
    if (layout !== lastEffective) {
        lastEffective = layout;
        const fit = (drawerEnv() as { TerminalLayout?: { requestFit?(why: string): void } }).TerminalLayout;
        if (fit && typeof fit.requestFit === 'function') fit.requestFit('sidebar-pin');
    }
    if (sidebar && sidebar.backdrop) sidebar.backdrop.hidden = !sidebar.isOpen || effective;
}

export function closeAfterSwitch(): void {
    if (isEffectivelyPinned()) return;
    const drawer = drawerNow();
    if (!drawer) return;
    drawer.close(drawer._transientOpen ? { persist: false } : undefined);
}

export function init(): void {
    if (!watching) {
        watching = true;
        window.addEventListener('resize', () => apply());
        const toggle = drawerNow()?.toggleBtn;
        if (toggle && typeof MutationObserver === 'function') {
            new MutationObserver(() => apply()).observe(toggle, { attributes: true, attributeFilter: ['class'] });
        }
    }
    apply();
}

export function reset(): void {
    lastEffective = null;
    watching = false;
}

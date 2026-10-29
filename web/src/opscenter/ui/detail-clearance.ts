
export const TOAST_COLUMN_ROOM = 392;
export const CLEAR_ATTR = 'data-toast-clear';
export const CLEAR_PROP = '--oc-toast-clear-right';

export type Clearance = { mode: 'side'; right: number } | { mode: 'full' };

export function clearanceFor(paneLeft: number, viewportWidth: number): Clearance {
    if (paneLeft < TOAST_COLUMN_ROOM) return { mode: 'full' };
    return { mode: 'side', right: Math.max(0, Math.round(viewportWidth - paneLeft)) };
}

const open = new Set<HTMLElement>();

function publish(): void {
    const root = document.documentElement;
    const pane = open.values().next().value as HTMLElement | undefined;
    if (!pane) {
        root.removeAttribute(CLEAR_ATTR);
        root.style.removeProperty(CLEAR_PROP);
        return;
    }
    const next = clearanceFor(pane.getBoundingClientRect().left, window.innerWidth);
    root.setAttribute(CLEAR_ATTR, next.mode);
    if (next.mode === 'side') root.style.setProperty(CLEAR_PROP, `${next.right}px`);
    else root.style.removeProperty(CLEAR_PROP);
}

export function clearToasts(node: HTMLElement): { destroy: () => void } {
    open.add(node);
    publish();
    const watch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publish);
    watch?.observe(node);
    window.addEventListener('resize', publish);
    return {
        destroy(): void {
            watch?.disconnect();
            window.removeEventListener('resize', publish);
            open.delete(node);
            publish();
        },
    };
}

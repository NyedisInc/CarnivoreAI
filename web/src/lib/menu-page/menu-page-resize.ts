const KEY_PREFIX = 'carnivore.menu-page.width.';
const STEP_PX = 16;

export function clampWidth(px: number, lo: number, hi: number): number {
    return Math.min(Math.max(hi, lo), Math.max(lo, px));
}

export function readDrawerWidth(id: string, storage: Pick<Storage, 'getItem'> = window.localStorage): number | null {
    try {
        const raw = storage.getItem(KEY_PREFIX + id);
        const n = raw == null ? NaN : Number(raw);
        return Number.isFinite(n) && n > 0 ? n : null;
    } catch {
        return null;
    }
}

export function writeDrawerWidth(id: string, px: number | null, storage: Pick<Storage, 'setItem' | 'removeItem'> = window.localStorage): void {
    try {
        if (px == null) storage.removeItem(KEY_PREFIX + id);
        else storage.setItem(KEY_PREFIX + id, String(Math.round(px)));
    } catch {
    }
}

export function drawerResize(root: () => HTMLElement | undefined) {
    return (handle: HTMLElement): (() => void) => {
        const page = root();
        if (!page) return () => {};
        const id = page.parentElement?.id ?? '';
        const bounds = (): { lo: number; hi: number; left: number } => {
            const rect = page.getBoundingClientRect();
            const right = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--menu-surface-right')) || 0;
            return { lo: parseFloat(getComputedStyle(page).minWidth) || 0, hi: Math.min(window.innerWidth - rect.left - right, parseFloat(getComputedStyle(page).maxWidth) || Infinity), left: rect.left };
        };
        const paint = (px: number): number => {
            const b = bounds();
            const w = clampWidth(px, b.lo, b.hi);
            page.style.setProperty('--oc-drawer-w', `${w}px`);
            handle.setAttribute('aria-valuenow', String(Math.round(w)));
            return w;
        };
        const stored = readDrawerWidth(id);
        if (stored != null) paint(stored);
        let dragging = false;
        const down = (e: PointerEvent): void => {
            if (e.button != null && e.button !== 0) return;
            dragging = true;
            try {
                handle.setPointerCapture(e.pointerId);
            } catch {
            }
            e.preventDefault();
        };
        const move = (e: PointerEvent): void => {
            if (dragging) paint(e.clientX - bounds().left);
        };
        const up = (e: PointerEvent): void => {
            if (!dragging) return;
            dragging = false;
            writeDrawerWidth(id, paint(e.clientX - bounds().left));
        };
        const key = (e: KeyboardEvent): void => {
            const now = page.getBoundingClientRect().width;
            const next = e.key === 'ArrowRight' ? now + STEP_PX : e.key === 'ArrowLeft' ? now - STEP_PX : null;
            if (next == null) return;
            e.preventDefault();
            writeDrawerWidth(id, paint(next));
        };
        const reset = (): void => {
            writeDrawerWidth(id, null);
            page.style.removeProperty('--oc-drawer-w');
        };
        handle.addEventListener('pointerdown', down);
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
        handle.addEventListener('pointercancel', up);
        handle.addEventListener('keydown', key);
        handle.addEventListener('dblclick', reset);
        return () => {
            handle.removeEventListener('pointerdown', down);
            handle.removeEventListener('pointermove', move);
            handle.removeEventListener('pointerup', up);
            handle.removeEventListener('pointercancel', up);
            handle.removeEventListener('keydown', key);
            handle.removeEventListener('dblclick', reset);
        };
    };
}

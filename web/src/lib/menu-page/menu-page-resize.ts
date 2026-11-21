import { onWidthChange, readDrawerWidth, writeDrawerWidth } from './menu-page-width';

const STEP_PX = 16;

export function clampWidth(px: number, lo: number, hi: number): number {
    return Math.min(Math.max(hi, lo), Math.max(lo, px));
}

const DRAG_SLOP_PX = 2;
const KEY_SAVE_MS = 300;

export function drawerResize(root: () => HTMLElement | undefined) {
    return (handle: HTMLElement): (() => void) => {
        const page = root();
        if (!page) return () => {};
        const offset = (): number => parseFloat(getComputedStyle(page).getPropertyValue('--oc-drawer-offset')) || parseFloat(page.style.getPropertyValue('--oc-drawer-offset')) || 0;
        const bounds = (): { lo: number; hi: number; left: number } => {
            const rect = page.getBoundingClientRect();
            const right = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--menu-surface-right')) || 0;
            return { lo: parseFloat(getComputedStyle(page).minWidth) || 0, hi: Math.min(window.innerWidth - rect.left - right, parseFloat(getComputedStyle(page).maxWidth) || Infinity), left: rect.left };
        };
        const paintWidth = (px: number): number => {
            const b = bounds();
            const w = clampWidth(px, b.lo, b.hi);
            page.style.setProperty('--oc-drawer-w', `${w}px`);
            handle.setAttribute('aria-valuenow', String(Math.round(w)));
            return w;
        };
        const paintShared = (shared: number | null): void => {
            if (shared == null) page.style.removeProperty('--oc-drawer-w');
            else paintWidth(shared - offset());
        };
        const save = (width: number): void => writeDrawerWidth(width + offset());
        paintShared(readDrawerWidth());
        const unfollow = onWidthChange(paintShared);
        let dragging = false;
        let startX = 0;
        let moved = false;
        let painted = 0;
        const endDrag = (): void => {
            dragging = false;
            handle.removeAttribute('data-dragging');
        };
        const down = (e: PointerEvent): void => {
            if (e.button != null && e.button !== 0) return;
            dragging = true;
            moved = false;
            startX = e.clientX;
            handle.setAttribute('data-dragging', '');
            try {
                handle.setPointerCapture(e.pointerId);
            } catch {
            }
            e.preventDefault();
        };
        const move = (e: PointerEvent): void => {
            if (!dragging) return;
            if (Math.abs(e.clientX - startX) > DRAG_SLOP_PX) moved = true;
            if (moved) painted = paintWidth(e.clientX - bounds().left);
        };
        const up = (e: PointerEvent): void => {
            if (!dragging) return;
            endDrag();
            if (!moved) return;
            painted = paintWidth(e.clientX - bounds().left);
            save(painted);
        };
        const cancel = (): void => {
            if (!dragging) return;
            endDrag();
            paintShared(readDrawerWidth());
        };
        let pending: number | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const flush = (): void => {
            clearTimeout(timer);
            timer = undefined;
            if (pending != null) save(pending);
            pending = null;
        };
        const key = (e: KeyboardEvent): void => {
            const now = page.getBoundingClientRect().width;
            const next = e.key === 'ArrowRight' ? now + STEP_PX : e.key === 'ArrowLeft' ? now - STEP_PX : null;
            if (next == null) return;
            e.preventDefault();
            pending = paintWidth(next);
            clearTimeout(timer);
            timer = setTimeout(flush, KEY_SAVE_MS);
        };
        const keyUp = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') flush();
        };
        const reset = (): void => {
            pending = null;
            writeDrawerWidth(null);
            page.style.removeProperty('--oc-drawer-w');
        };
        handle.addEventListener('pointerdown', down);
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
        handle.addEventListener('pointercancel', cancel);
        handle.addEventListener('keydown', key);
        handle.addEventListener('keyup', keyUp);
        handle.addEventListener('dblclick', reset);
        return () => {
            flush();
            unfollow();
            handle.removeEventListener('pointerdown', down);
            handle.removeEventListener('pointermove', move);
            handle.removeEventListener('pointerup', up);
            handle.removeEventListener('pointercancel', cancel);
            handle.removeEventListener('keydown', key);
            handle.removeEventListener('keyup', keyUp);
            handle.removeEventListener('dblclick', reset);
        };
    };
}

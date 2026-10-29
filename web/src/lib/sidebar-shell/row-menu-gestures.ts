import { isMenuKey } from '../zone-shell/key-nav';
import { openRowMenuFromTrigger, rowMenuOpenFor } from '../item-menu/row-open';
import { TRIGGER_ATTR } from '../item-menu/row-context';

export const LONG_PRESS_MS = 500;
export const MOVE_SLOP_PX = 10;

let press: { x: number; y: number; timer: ReturnType<typeof setTimeout> } | null = null;
let swallowClick = false;

function coarsePointer(): boolean {
    return typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
}

function pressExempt(target: Element | null): boolean {
    if (!target || typeof target.closest !== 'function') return true;
    if (target.closest('[data-grip-session]')) return true;
    return !!target.closest('button, input, textarea, select, [role="button"]');
}

export function rowKebab(target: EventTarget | null): Element | null {
    const el = target as Element | null;
    if (!el || typeof el.closest !== 'function') return null;
    const row = el.closest('.session-sidebar-row');
    return row ? row.querySelector(`[${TRIGGER_ATTR}]`) : null;
}

export function cancelPress(): void {
    if (!press) return;
    clearTimeout(press.timer);
    press = null;
}

export function onClickCapture(e: MouseEvent): void {
    if (!swallowClick) return;
    swallowClick = false;
    e.preventDefault();
    e.stopPropagation();
}

export function onContextMenu(e: MouseEvent): void {
    if (e.defaultPrevented) return;
    const kebab = rowKebab(e.target);
    if (!kebab) return;
    e.preventDefault();
    cancelPress();
    if (rowMenuOpenFor(kebab)) return;
    openRowMenuFromTrigger(kebab, coarsePointer() ? null : { x: e.clientX, y: e.clientY });
}

export function startLongPress(e: PointerEvent, open: () => void): void {
    swallowClick = false;
    cancelPress();
    if (e.pointerType === 'mouse' || pressExempt(e.target as Element | null)) return;
    press = {
        x: e.clientX,
        y: e.clientY,
        timer: setTimeout(() => {
            press = null;
            swallowClick = true;
            open();
        }, LONG_PRESS_MS),
    };
}

export function onPointerDown(e: PointerEvent): void {
    swallowClick = false;
    cancelPress();
    const kebab = rowKebab(e.target);
    if (kebab) startLongPress(e, () => { openRowMenuFromTrigger(kebab); });
}

export function onPointerMove(e: PointerEvent): void {
    if (!press) return;
    const dx = e.clientX - press.x;
    const dy = e.clientY - press.y;
    if (dx * dx + dy * dy > MOVE_SLOP_PX * MOVE_SLOP_PX) cancelPress();
}

export function onMenuKey(e: KeyboardEvent): boolean {
    if (!isMenuKey(e) || pressExempt(e.target as Element | null)) return false;
    const kebab = rowKebab(e.target);
    if (!kebab) return false;
    e.preventDefault();
    if (!rowMenuOpenFor(kebab)) openRowMenuFromTrigger(kebab);
    return true;
}

import { BAR_GRAB_MIN_PX, maxBarPx } from '../session-rail/bar-limits';
import { sideBudget } from '../session-rail/side-budget.svelte';

export const STORAGE_KEY = 'carnivore.session.sidebar.width';
export const MIN_WIDTH_PX = BAR_GRAB_MIN_PX;
export const DEFAULT_WIDTH_PX = 320;
const STEP_PX = 16;

let handleEl: HTMLElement | null = null;
let dragging = false;
let wanted = DEFAULT_WIDTH_PX;

export function maxWidth(): number {
    return maxBarPx(window.innerWidth - sideBudget.otherThan('drawer'), 'x');
}

export function clamp(px: number): number {
    return Math.min(maxWidth(), Math.max(MIN_WIDTH_PX, px));
}

export function readWidth(): number | null {
    let raw: string | null = null;
    try {
        raw = window.localStorage.getItem(STORAGE_KEY);
    } catch {
        return null;
    }
    if (raw == null) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? clamp(n) : null;
}

export function writeWidth(px: number): void {
    try {
        window.localStorage.setItem(STORAGE_KEY, String(Math.round(px)));
    } catch {
    }
}

export function clearWidth(): void {
    try {
        window.localStorage.removeItem(STORAGE_KEY);
    } catch {
    }
}

export function apply(px: number): number {
    wanted = px;
    return paint(px);
}

function paint(px: number): number {
    const clamped = clamp(px);
    sideBudget.hold('drawer', clamped);
    document.documentElement.style.setProperty('--sidebar-dock-w', `min(${clamped}px, 100vw)`);
    if (handleEl) handleEl.setAttribute('aria-valuenow', String(Math.round(clamped)));
    if (handleEl) handleEl.setAttribute('aria-valuemax', String(maxWidth()));
    return clamped;
}

export function refit(): void {
    paint(wanted);
}

function restore(): void {
    const stored = readWidth();
    apply(stored == null ? DEFAULT_WIDTH_PX : stored);
}

function announce(px: number): void {
    const region = document.getElementById('session-sidebar-live');
    if (region) region.textContent = `sidebar width ${Math.round(px)} pixels`;
}

function onPointerDown(e: PointerEvent): void {
    if (e.button != null && e.button !== 0) return;
    dragging = true;
    if (handleEl && handleEl.setPointerCapture) {
        try {
            handleEl.setPointerCapture(e.pointerId);
        } catch {
        }
    }
    document.body.classList.add('session-sidebar-resizing');
    e.preventDefault();
}

function onPointerMove(e: PointerEvent): void {
    if (!dragging) return;
    apply(e.clientX);
}

function onPointerUp(e: PointerEvent): void {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('session-sidebar-resizing');
    const final = apply(e.clientX);
    writeWidth(final);
    announce(final);
}

function onKeydown(e: KeyboardEvent): void {
    if (!handleEl) return;
    const current = clamp(parseFloat(handleEl.getAttribute('aria-valuenow') || '') || DEFAULT_WIDTH_PX);
    let next: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = current + STEP_PX;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = current - STEP_PX;
    else if (e.key === 'Home') next = MIN_WIDTH_PX;
    else if (e.key === 'End') next = maxWidth();
    if (next == null) return;
    e.preventDefault();
    const applied = apply(next);
    writeWidth(applied);
    announce(applied);
}

function onDblClick(): void {
    clearWidth();
    announce(apply(DEFAULT_WIDTH_PX));
}

export function init(): void {
    restore();
    if (handleEl) return;
    handleEl = document.getElementById('session-sidebar-resize-handle');
    if (!handleEl) return;
    window.addEventListener('resize', refit);
    handleEl.addEventListener('pointerdown', onPointerDown);
    handleEl.addEventListener('pointermove', onPointerMove);
    handleEl.addEventListener('pointerup', onPointerUp);
    handleEl.addEventListener('pointercancel', onPointerUp);
    handleEl.addEventListener('keydown', onKeydown);
    handleEl.addEventListener('dblclick', onDblClick);
    handleEl.setAttribute('aria-valuemin', String(MIN_WIDTH_PX));
    handleEl.setAttribute('aria-valuemax', String(maxWidth()));
    const current = readWidth();
    handleEl.setAttribute('aria-valuenow', String(current == null ? DEFAULT_WIDTH_PX : current));
}

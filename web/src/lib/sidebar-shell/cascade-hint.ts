
export const CHEVRON_PATH = 'M4 2l4 4-4 4';

export const CASCADE_PATH = 'M2 2l4 4-4 4M6 2l4 4-4 4';

const CHEVRON_SELECTOR = '.session-sidebar-group__chevron path';

const rows = new Map<HTMLElement, { hover: boolean; focus: boolean }>();

let shiftHeld = false;

let listening = false;

function paint(row: HTMLElement): void {
    const s = rows.get(row);
    const on = shiftHeld && !!s && (s.hover || s.focus);
    const path = row.querySelector(CHEVRON_SELECTOR);
    if (path) path.setAttribute('d', on ? CASCADE_PATH : CHEVRON_PATH);
    if (on) row.setAttribute('data-cascade', '1');
    else row.removeAttribute('data-cascade');
}

function setShift(held: boolean): void {
    if (held === shiftHeld) return;
    shiftHeld = held;
    rows.forEach((_s, row) => paint(row));
}

function onWindowKey(e: KeyboardEvent): void { setShift(e.shiftKey); }
function onWindowPointer(e: MouseEvent): void { setShift(e.shiftKey); }
function onWindowBlur(): void { setShift(false); }

function listen(): void {
    if (listening) return;
    listening = true;
    window.addEventListener('keydown', onWindowKey, true);
    window.addEventListener('keyup', onWindowKey, true);
    window.addEventListener('pointermove', onWindowPointer, true);
    window.addEventListener('blur', onWindowBlur);
}

export function watchCascadeHint(row: HTMLElement): () => void {
    listen();
    const state = { hover: false, focus: false };
    rows.set(row, state);
    const set = (patch: Partial<typeof state>): void => { Object.assign(state, patch); paint(row); };
    const enter = (e: PointerEvent): void => { setShift(e.shiftKey); set({ hover: true }); };
    const leave = (): void => set({ hover: false });
    const focusIn = (): void => set({ focus: true });
    const focusOut = (): void => set({ focus: false });
    row.addEventListener('pointerenter', enter);
    row.addEventListener('pointerleave', leave);
    row.addEventListener('focusin', focusIn);
    row.addEventListener('focusout', focusOut);
    paint(row);
    return () => {
        row.removeEventListener('pointerenter', enter);
        row.removeEventListener('pointerleave', leave);
        row.removeEventListener('focusin', focusIn);
        row.removeEventListener('focusout', focusOut);
        rows.delete(row);
    };
}

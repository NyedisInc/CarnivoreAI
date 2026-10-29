import { closeItemMenu, itemMenuState, openItemMenu, openItemMenuContext, refreshItemMenu, type ItemMenuOpenOptions } from './open.svelte';
import {
    contextFromTrigger, ROW_MENU_TYPES as ROW_TYPES, rowMenuType, TRIGGER_ATTR, TRIGGER_UPDATE_CLASS, updateTitle, type RowMenuCtx,
} from './row-context';

export const SHIFT_ATTR = 'data-shift-restart';


interface OpenGlobals {
    SessionRowMenuActions?: { run(id: string, ctx: RowMenuCtx, opts?: Record<string, unknown>): Promise<unknown> | unknown };
}

let shiftApplied = false;

export function shiftHeld(): boolean {
    return shiftApplied;
}

export function applyShift(held: boolean): void {
    if (held === shiftApplied) return;
    shiftApplied = held;
    const open = itemMenuState.open;
    if (open && ROW_TYPES.has(open.type) && (openItemMenuContext() as RowMenuCtx | null)?.shiftHeld !== held) refreshItemMenu({ shiftHeld: held });
    for (const el of document.querySelectorAll(`.${TRIGGER_UPDATE_CLASS}`)) {
        if (held) el.setAttribute(SHIFT_ATTR, '1');
        else el.removeAttribute(SHIFT_ATTR);
        const label = updateTitle(el.getAttribute('data-row-menu-update-running') || '', el.getAttribute('data-row-menu-update-installed') || '', held);
        el.setAttribute('data-tooltip', label);
        el.setAttribute('aria-label', label);
    }
}

export function rowMenuIsOpen(): boolean {
    const open = itemMenuState.open;
    return !!open && ROW_TYPES.has(open.type);
}

export function closeRowMenu(): void {
    if (rowMenuIsOpen()) closeItemMenu();
}

export function rowMenuOpenFor(trigger: Element): boolean {
    const open = itemMenuState.open;
    if (!open || !ROW_TYPES.has(open.type)) return false;
    const name = trigger.getAttribute(TRIGGER_ATTR);
    return open.anchor === trigger || (!!name && (openItemMenuContext() as RowMenuCtx | null)?.name === name);
}

export function openRowMenuFromTrigger(trigger: Element, at: { x: number; y: number } | null = null, opts: ItemMenuOpenOptions = {}): boolean {
    const ctx = contextFromTrigger(trigger);
    if (!ctx || !ctx.name) return false;
    return openRowMenu(ctx, trigger, at, opts);
}

export function openRowMenu(ctx: RowMenuCtx, anchor: Element, at: { x: number; y: number } | null = null, opts: ItemMenuOpenOptions = {}): boolean {
    if (!ctx.name) return false;
    return openItemMenu(rowMenuType(ctx), { ...ctx, shiftHeld: shiftApplied }, anchor, at, opts);
}

export function onTriggerClickCapture(e: MouseEvent): void {
    const target = e.target as Element | null;
    if (!target || typeof target.closest !== 'function') return;
    const trigger = target.closest(`[${TRIGGER_ATTR}]`);
    if (!trigger) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey && trigger.getAttribute('data-row-menu-update-ready') === '1' && trigger.getAttribute('data-row-menu-update-busy') !== '1') {
        const actions = (globalThis as unknown as OpenGlobals).SessionRowMenuActions;
        const ctx = contextFromTrigger(trigger);
        if (actions && ctx) {
            Promise.resolve(actions.run('update-restart', ctx, { armedByGesture: true }))
                .catch((err: unknown) => console.error('[item-menu] shift-click update restart failed:', err));
            return;
        }
    }
    if (rowMenuOpenFor(trigger)) {
        closeItemMenu();
        return;
    }
    openRowMenuFromTrigger(trigger);
}

function onShiftKey(e: KeyboardEvent | PointerEvent): void {
    applyShift(!!e.shiftKey);
}

function onBlur(): void {
    applyShift(false);
}

let installed = false;

export function installRowMenuOpener(): () => void {
    if (installed) return () => undefined;
    installed = true;
    document.addEventListener('click', onTriggerClickCapture, true);
    window.addEventListener('keydown', onShiftKey, true);
    window.addEventListener('keyup', onShiftKey, true);
    window.addEventListener('pointerdown', onShiftKey, true);
    window.addEventListener('blur', onBlur);
    return () => {
        installed = false;
        document.removeEventListener('click', onTriggerClickCapture, true);
        window.removeEventListener('keydown', onShiftKey, true);
        window.removeEventListener('keyup', onShiftKey, true);
        window.removeEventListener('pointerdown', onShiftKey, true);
        window.removeEventListener('blur', onBlur);
    };
}

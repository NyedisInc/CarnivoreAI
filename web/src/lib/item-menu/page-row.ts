import { isMenuKey } from '../zone-shell/key-nav';
import { cancelPress, onClickCapture, onPointerMove, startLongPress } from '../sidebar-shell/row-menu-gestures';
import { openItemMenu } from './open.svelte';
import { openRowMenu } from './row-open';
import type { RowMenuCtx } from './row-context';
import type { PageRowCtx } from './types';

export type PageRowMenu =
    | { type: 'session'; ctx: RowMenuCtx; onOpen?: () => void }
    | { type: 'pagerow'; ctx: PageRowCtx; onOpen?: () => void };

export type PageRowSource = () => PageRowMenu | null;

export function openPageRowMenu(menu: PageRowMenu, anchor: Element, at: { x: number; y: number }): boolean {
    menu.onOpen?.();
    return menu.type === 'session' ? openRowMenu(menu.ctx, anchor, at) : openItemMenu('pagerow', menu.ctx, anchor, at);
}

export function pageRowMenu(source: PageRowSource): Record<string, (event: never) => void> {
    return {
        oncontextmenu(event: MouseEvent): void {
            cancelPress();
            const menu = source();
            if (!menu || !openPageRowMenu(menu, event.currentTarget as Element, { x: event.clientX, y: event.clientY })) return;
            event.preventDefault();
            event.stopPropagation();
        },
        onpointerdown(event: PointerEvent): void {
            const row = event.currentTarget as Element;
            const { clientX: x, clientY: y } = event;
            startLongPress(event, () => {
                const menu = source();
                if (menu) openPageRowMenu(menu, row, { x, y });
            });
        },
        onpointermove: onPointerMove,
        onpointerup: cancelPress,
        onpointercancel: cancelPress,
        onclickcapture: onClickCapture,
    };
}

export function rightClickMenu(source: PageRowSource): Record<string, (event: never) => void> {
    const { oncontextmenu } = pageRowMenu(source);
    return { oncontextmenu };
}

export function forwardMenuKey(event: KeyboardEvent, row: Element | null): boolean {
    if (!isMenuKey(event) || !row) return false;
    const box = row.getBoundingClientRect();
    event.preventDefault();
    row.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: box.left + 24, clientY: box.top + box.height / 2 }));
    return true;
}

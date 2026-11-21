import { isMenuKey } from '../zone-shell/key-nav';

export interface MenuPoint {
    readonly x: number;
    readonly y: number;
}

/* the widget menu */
export type OpenWidgetMenu = (at: MenuPoint | null, from: HTMLElement) => void;

function headerDoor(from: HTMLElement): HTMLElement | null {
    const tab = tabDoor(from);
    if (tab !== undefined) return tab;
    return from.closest<HTMLElement>('[data-cell]')?.querySelector<HTMLElement>('[data-corner]') ?? null;
}

function tabDoor(from: HTMLElement): HTMLElement | null | undefined {
    if (!from.closest('[data-widget-tab]')) return undefined;
    const key = from.closest<HTMLElement>('[data-tab-pane]')?.dataset.tabPane;
    const cell = from.closest<HTMLElement>('[data-cell]');
    const tab = key ? [...(cell?.querySelectorAll<HTMLElement>('[data-tab]') ?? [])].find((el) => el.dataset.tab === key) : undefined;
    return tab?.parentElement?.querySelector<HTMLElement>('[data-corner]') ?? null;
}

/* the widget menu */
export const openWidgetMenu: OpenWidgetMenu = (at, from) => {
    const door = headerDoor(from);
    if (door) {
        if (door.getAttribute('aria-expanded') !== 'true') door.click();
        return;
    }
    const box = from.getBoundingClientRect();
    const point = at ?? { x: box.left, y: box.bottom };
    from.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: point.x, clientY: point.y }));
};

export function widgetMenuGesture(open: OpenWidgetMenu): { oncontextmenu: (event: MouseEvent) => void; onkeydown: (event: KeyboardEvent) => void } {
    return {
        oncontextmenu(event) {
            event.preventDefault();
            open({ x: event.clientX, y: event.clientY }, event.currentTarget as HTMLElement);
        },
        onkeydown(event) {
            if (!isMenuKey(event)) return;
            event.preventDefault();
            open(null, event.currentTarget as HTMLElement);
        },
    };
}

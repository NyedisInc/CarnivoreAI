import { MODAL_SELECTOR } from '../sidebar-widgets/escape-guards';
import { FLYOUT_CONTAINER_ID, RAIL_CONTAINER_ID } from '../sidebar-widgets/rail-dom';
import { MENU_PAGES } from './menu-pages';

const BAR_SLOT_ID = 'session-sidebar-bar-slot';

const SPAWNED_SELECTOR = `${MODAL_SELECTOR}, [role="menu"], [role="listbox"]:not(#session-sidebar-list), [role="dialog"], [popover], .mr[role="presentation"], [data-rail-item], [data-rail-key], [data-rail-widget]`;

export interface OutsideDeps {
    slideOutOpen: () => boolean;
    close: () => void;
}

export function pressIsOutside(target: EventTarget | null, doc: Document): boolean {
    if (!(target instanceof Element) || !target.isConnected) return false;
    if (target.closest(SPAWNED_SELECTOR)) return false;
    const insideIds = [...MENU_PAGES.map((p) => p.containerId), FLYOUT_CONTAINER_ID, RAIL_CONTAINER_ID, BAR_SLOT_ID];
    return !insideIds.some((id) => doc.getElementById(id)?.contains(target));
}

export function handleMenuPageOutsidePress(event: Event, deps: OutsideDeps, doc: Document = document): boolean {
    if (!deps.slideOutOpen() || !pressIsOutside(event.target, doc)) return false;
    deps.close();
    return true;
}

export function initMenuPageOutside(doc: Document, deps: OutsideDeps): () => void {
    const onPress = (event: Event): void => {
        handleMenuPageOutsidePress(event, deps, doc);
    };
    doc.addEventListener('pointerdown', onPress, true);
    return () => doc.removeEventListener('pointerdown', onPress, true);
}

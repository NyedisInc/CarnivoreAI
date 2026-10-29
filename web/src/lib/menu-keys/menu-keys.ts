
import { assignMenuKeys, registeredKey } from '../../../../client/js/menu-keys.js';

export { assignMenuKeys, registeredKey };

function typing(target: EventTarget | null): boolean {
    const el = target as HTMLElement | null;
    if (!el || !el.tagName) return false;
    return /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable === true;
}

export function pressMenuKey(event: KeyboardEvent, panel: HTMLElement | null | undefined): boolean {
    if (!panel || event.metaKey || event.ctrlKey || event.altKey || event.isComposing || typing(event.target)) return false;
    if (event.key.length !== 1) return false;
    const key = event.key.toLowerCase();
    const item = [...panel.querySelectorAll<HTMLElement>('[data-menu-key]')].find(
        (el) => el.dataset.menuKey === key && el.closest('[role="menu"]') === panel,
    );
    if (!item || item.getAttribute('aria-disabled') === 'true' || (item as HTMLButtonElement).disabled) return false;
    event.preventDefault();
    event.stopPropagation();
    item.focus();
    item.click();
    return true;
}

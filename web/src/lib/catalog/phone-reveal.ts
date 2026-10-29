/* the reading pane */

const PHONE_QUERY = '(max-width: 767px)';

/* the reading pane */
export function revealOnPhone(node: HTMLElement): void {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    if (!window.matchMedia(PHONE_QUERY).matches) return;
    const screen = node.closest<HTMLElement>('.oc-page');
    if (!screen) return;
    const strip = screen.querySelector<HTMLElement>('.oc-titlebar');
    const covered = strip && getComputedStyle(strip).position === 'sticky' ? strip.getBoundingClientRect().height : 0;
    const offset = node.getBoundingClientRect().top - screen.getBoundingClientRect().top - covered;
    screen.scrollTop += offset;
}

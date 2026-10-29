import { initialAway, nextAway } from '../../../../client/js/scroll-away.js';

export function watchScrollAway(root: HTMLElement, rows: HTMLElement, report: (away: boolean) => void): () => void {
    let state = initialAway();
    let last: EventTarget | null = null;
    let shown = false;

    function put(next: { away: boolean; anchor: number }): void {
        state = next;
        if (next.away !== shown) {
            shown = next.away;
            report(shown);
        }
    }

    function onScroll(event: Event): void {
        const el = event.target;
        if (!(el instanceof HTMLElement) || rows.contains(el)) return;
        const top = el.scrollTop;
        const rowsH = rows.offsetHeight;
        if (last !== null && el !== last) state = { away: state.away, anchor: top };
        last = el;
        put(nextAway(state, { top, max: el.scrollHeight - el.clientHeight, rowsH, focusInside: rows.contains(document.activeElement) }));
    }

    function bringBack(): void {
        put({ away: false, anchor: state.anchor });
    }

    root.addEventListener('scroll', onScroll, { capture: true, passive: true });
    rows.addEventListener('focusin', bringBack);
    rows.addEventListener('click', bringBack);
    return () => {
        root.removeEventListener('scroll', onScroll, { capture: true });
        rows.removeEventListener('focusin', bringBack);
        rows.removeEventListener('click', bringBack);
        put(initialAway());
    };
}

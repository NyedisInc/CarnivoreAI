import { MOBILE_MAX_PX } from '../drawer/pin';

export const COMPACT_EXIT_MARGIN_PX = 16;

export const COMPACT_CLASS = 'sp-bar--compact';

export function nextCompact(compact: boolean, barWidth: number, need: number, phone: boolean): boolean {
    if (phone || barWidth <= 0) return false;
    return compact ? barWidth < need + COMPACT_EXIT_MARGIN_PX : need > barWidth;
}

function rowWidth(el: Element | null, gap: number): number {
    if (!el) return 0;
    const kids = [...el.children];
    return kids.reduce((sum, kid) => sum + kid.getBoundingClientRect().width, 0) + gap * Math.max(0, kids.length - 1);
}

export function labelledNeed(bar: HTMLElement): number {
    const style = getComputedStyle(bar);
    const gap = parseFloat(style.columnGap) || 0;
    const facets = bar.querySelector('.oc-toolbar__facets');
    const end = bar.querySelector('.oc-toolbar__end');
    const facetsGap = facets ? parseFloat(getComputedStyle(facets).columnGap) || 0 : 0;
    const endGap = end ? parseFloat(getComputedStyle(end).columnGap) || 0 : 0;
    const pad = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
    return pad + rowWidth(facets, facetsGap) + gap + rowWidth(end, endGap);
}

export function watchBarFit(bar: HTMLElement, onChange: (compact: boolean) => void): (() => void) | undefined {
    if (typeof ResizeObserver === 'undefined') return undefined;
    let compact = false;
    let labelledAtEntry: number | null = null;
    let labelsDelta = 0;
    let frame = 0;
    const settle = (): void => {
        const phone = window.innerWidth <= MOBILE_MAX_PX;
        const measured = labelledNeed(bar);
        let need = measured;
        if (compact) {
            if (labelledAtEntry !== null) {
                labelsDelta = Math.max(0, labelledAtEntry - measured);
                labelledAtEntry = null;
            }
            need = measured + labelsDelta;
        }
        const next = nextCompact(compact, bar.clientWidth, need, phone);
        if (next === compact) return;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            compact = next;
            labelledAtEntry = next ? need : null;
            onChange(next);
        });
    };
    const watch = new ResizeObserver(settle);
    watch.observe(bar);
    for (const part of bar.querySelectorAll('.oc-toolbar__facets, .oc-toolbar__end')) watch.observe(part);
    void document.fonts?.ready.then(settle);
    return () => {
        cancelAnimationFrame(frame);
        watch.disconnect();
    };
}

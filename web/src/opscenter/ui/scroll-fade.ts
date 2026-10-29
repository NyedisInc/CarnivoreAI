
/*  hidden  */
export function fadeEdges(el: HTMLElement): { start: boolean; end: boolean } {
    return {
        start: el.scrollLeft > 1,
        end: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
    };
}

export function revealSideways(scroller: HTMLElement, item: HTMLElement | null): void {
    if (!item) return;
    const box = scroller.getBoundingClientRect();
    const rect = item.getBoundingClientRect();
    if (rect.left < box.left) scroller.scrollLeft -= box.left - rect.left;
    else if (rect.right > box.right) scroller.scrollLeft += Math.min(rect.right - box.right, rect.left - box.left);
}

export function scrollFade(node: HTMLElement): { destroy: () => void } {
    function measure(): void {
        const { start, end } = fadeEdges(node);
        node.classList.toggle('oc-fade-start', start);
        node.classList.toggle('oc-fade-end', end);
    }
    node.addEventListener('scroll', measure, { passive: true });
    const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    sizes?.observe(node);
    for (const child of Array.from(node.children)) sizes?.observe(child);
    const kids = typeof MutationObserver === 'undefined' ? null : new MutationObserver(() => {
        sizes?.disconnect();
        sizes?.observe(node);
        for (const child of Array.from(node.children)) sizes?.observe(child);
        measure();
    });
    kids?.observe(node, { childList: true });
    measure();
    return {
        destroy(): void {
            node.removeEventListener('scroll', measure);
            sizes?.disconnect();
            kids?.disconnect();
        },
    };
}

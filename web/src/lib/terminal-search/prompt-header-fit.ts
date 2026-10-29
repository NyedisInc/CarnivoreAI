
export function isCutOff(el: HTMLElement | null): boolean {
    if (!el) return false;
    return el.scrollWidth > el.clientWidth;
}

export function hasTypedBreak(full: string): boolean {
    return full.includes('\n');
}

export function watchBox(
    el: HTMLElement | null,
    onChange: () => void,
): (() => void) | undefined {
    const Observer = el?.ownerDocument?.defaultView?.ResizeObserver;
    if (!el || !Observer) return undefined;
    const observer = new Observer(() => onChange());
    observer.observe(el);
    return () => observer.disconnect();
}


const ATTR = 'data-motion';
const QUERY = '(prefers-reduced-motion: reduce)';

export function animationsOff(): boolean {
    return typeof document !== 'undefined' && document.documentElement?.getAttribute(ATTR) === 'off';
}

export function motionReduced(): boolean {
    if (animationsOff()) return true;
    return typeof matchMedia === 'function' && matchMedia(QUERY).matches;
}

export function watchMotion(onChange: (reduced: boolean) => void): () => void {
    const fire = (): void => onChange(motionReduced());
    const query = typeof matchMedia === 'function' ? matchMedia(QUERY) : null;
    query?.addEventListener('change', fire);
    let observer: MutationObserver | null = null;
    if (typeof MutationObserver === 'function' && typeof document !== 'undefined' && document.documentElement) {
        observer = new MutationObserver(fire);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: [ATTR] });
    }
    return () => {
        query?.removeEventListener('change', fire);
        observer?.disconnect();
    };
}

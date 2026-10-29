import { isMobile } from './pin';

export type ViewClass = 'desktop' | 'mobile';

let source: (() => ViewClass) | null = null;
let latched: ViewClass | null = null;
let watching = false;

export function setViewClassSource(fn: (() => ViewClass) | null): void {
    source = fn;
    latched = null;
}

function measure(): ViewClass | null {
    if (source) return source();
    if (typeof window === 'undefined' || !window.innerWidth) return null;
    return isMobile() ? 'mobile' : 'desktop';
}

export function viewClass(): ViewClass {
    if (latched === null) latched = measure() || 'desktop';
    return latched;
}

export function watchViewClass(onFlip: (cls: ViewClass) => void): void {
    viewClass();
    if (watching || typeof window === 'undefined') return;
    watching = true;
    window.addEventListener('resize', () => {
        const next = measure();
        if (next === null || next === latched) return;
        latched = next;
        onFlip(next);
    });
}

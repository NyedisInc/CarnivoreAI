
export const ANIMATION_TYPES = [
    'status-lights',
    'avatar-spiral',
    'terminal-ring',
    'dialog-glow',
    'effort-badges',
    'drawer-bands',
    'sparks-steam',
    'busy-pulses',
    'attention-cues',
    'swarm-characters',
    'pop-ins',
    'transitions',
    'layout-moves',
    'theme-backdrop',
    'cursor-blink',
] as const;

export type AnimationType = (typeof ANIMATION_TYPES)[number];

const ATTR = 'data-anim-off';
const STORAGE_KEY = 'carnivore.animation-types-off';

function offIds(): string[] {
    if (typeof document === 'undefined') return [];
    return (document.documentElement.getAttribute(ATTR) ?? '').split(/\s+/).filter(Boolean);
}

export function animationTypeOff(id: AnimationType): boolean {
    return offIds().includes(id);
}

export function setAnimationTypeOff(id: AnimationType, off: boolean): void {
    const next = new Set(offIds());
    if (off) next.add(id);
    else next.delete(id);
    const list = ANIMATION_TYPES.filter((type) => next.has(type)).join(' ');
    try {
        if (list) localStorage.setItem(STORAGE_KEY, list);
        else localStorage.removeItem(STORAGE_KEY);
    } catch {
    }
    const root = document.documentElement;
    if (list) root.setAttribute(ATTR, list);
    else root.removeAttribute(ATTR);
}

export function watchAnimationTypes(onChange: () => void): () => void {
    if (typeof MutationObserver !== 'function' || typeof document === 'undefined') return () => {};
    const observer = new MutationObserver(onChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: [ATTR] });
    return () => observer.disconnect();
}

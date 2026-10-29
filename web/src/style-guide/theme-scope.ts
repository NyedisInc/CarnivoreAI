/* element carrying a */
import type { ThemeRegistry } from '../cplugs/sdk/themes';
import { scopeVars } from './contrast';

export interface GuideTheme {
    id: string;
    name: string;
    cssVars: Record<string, string>;
}

export type Rgb = [number, number, number];

const registry = (): ThemeRegistry | undefined => (globalThis as { Themes?: ThemeRegistry }).Themes;

export function guideThemes(): GuideTheme[] {
    return (registry()?.listAll?.() ?? []).map((m) => ({ id: m.id, name: m.name || m.id, cssVars: m.cssVars ?? {} }));
}

export function paintScope(el: HTMLElement, theme: GuideTheme, all: readonly GuideTheme[]): void {
    const names = new Set(all.flatMap((t) => Object.keys(t.cssVars)));
    el.dataset.sessionTheme = theme.id;
    for (const [name, value] of Object.entries(scopeVars(theme.cssVars, names))) el.style.setProperty(name, value);
}

export function onGuideTheme(cb: (id: string) => void): () => void {
    const handler = (event: Event): void => cb((event as CustomEvent<{ id: string }>).detail.id);
    document.addEventListener('style-guide:theme', handler);
    const now = document.documentElement.dataset.sgTheme;
    if (now) cb(now);
    return () => document.removeEventListener('style-guide:theme', handler);
}

export function colorReader(): { composite: (scope: HTMLElement, tokens: readonly string[]) => Rgb | null } {
    const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    return {
        composite(scope, tokens) {
            if (!ctx) return null;
            const probe = document.createElement('span');
            scope.appendChild(probe);
            try {
                ctx.clearRect(0, 0, 1, 1);
                ctx.fillStyle = '#000';
                ctx.fillRect(0, 0, 1, 1);
                for (const token of tokens) {
                    probe.style.color = `var(${token})`;
                    ctx.fillStyle = getComputedStyle(probe).color;
                    ctx.fillRect(0, 0, 1, 1);
                }
                const d = ctx.getImageData(0, 0, 1, 1).data;
                return [d[0] ?? 0, d[1] ?? 0, d[2] ?? 0];
            } finally {
                probe.remove();
            }
        },
    };
}

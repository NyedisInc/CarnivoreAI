import { fnv1a } from '../community/identicon';

export const ART_WIDTH = 288;
export const ART_HEIGHT = 96;

export const ART_TOKENS: readonly string[] = [
    '--oc-orange',
    '--oc-cyan',
    '--oc-green',
    '--oc-coral',
    '--oc-purple-light',
    '--oc-series-1',
    '--oc-series-2',
    '--oc-series-3',
];

export interface ArtShape {
    readonly kind: 'circle' | 'rect' | 'band';
    readonly x: number;
    readonly y: number;
    readonly size: number;
    readonly angle: number;
    readonly token: string;
    readonly opacity: number;
}

export function prng(seed: number): () => number {
    let state = seed >>> 0;
    return () => {
        state = (state + 0x6d2b79f5) >>> 0;
        let z = state;
        z = Math.imul(z ^ (z >>> 15), z | 1);
        z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
        return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
    };
}

const round = (value: number): number => Math.round(value * 10) / 10;

export function heroShapes(seed: string): ArtShape[] {
    const key = seed.trim().toLowerCase();
    const next = prng(fnv1a(`hero:${key}`));
    const pick = (): string => ART_TOKENS[Math.floor(next() * ART_TOKENS.length)] ?? ART_TOKENS[0]!;
    const shapes: ArtShape[] = [];
    for (let i = 0; i < 2; i += 1) {
        shapes.push({ kind: 'band', x: round(next() * ART_WIDTH), y: round(next() * ART_HEIGHT), size: round(8 + next() * 18), angle: round(-40 + next() * 80), token: pick(), opacity: round(0.25 + next() * 0.3) });
    }
    const count = 5 + Math.floor(next() * 3);
    for (let i = 0; i < count; i += 1) {
        const kind = next() < 0.55 ? 'circle' : 'rect';
        shapes.push({ kind, x: round(next() * ART_WIDTH), y: round(next() * ART_HEIGHT), size: round(7 + next() * 20), angle: round(next() * 90), token: pick(), opacity: round(0.35 + next() * 0.5) });
    }
    return shapes;
}

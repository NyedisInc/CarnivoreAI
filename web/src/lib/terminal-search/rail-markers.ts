import type { MarkerLike, RailPrompt, TermLike } from './types';

export function markerFor(
    term: TermLike,
    baseY: number,
    cursorY: number,
    line: number,
): MarkerLike | null {
    if (typeof term.registerMarker !== 'function') return null;
    try {
        return term.registerMarker(Math.round(line - baseY - cursorY)) ?? null;
    } catch {
        return null;
    }
}

export function lineOf(p: RailPrompt): number {
    if (p.marker && !p.marker.isDisposed && typeof p.marker.line === 'number') {
        return p.marker.line;
    }
    return p.line;
}

export function releaseMarkers(prompts: readonly RailPrompt[]): void {
    for (const p of prompts) {
        const m = p.marker;
        if (m && typeof m.dispose === 'function' && !m.isDisposed) {
            try {
                m.dispose();
            } catch {
            }
        }
    }
}

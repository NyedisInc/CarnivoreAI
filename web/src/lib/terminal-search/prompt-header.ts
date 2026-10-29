
export interface PlacedPrompt {
    ordinal: number;
    line: number;
}

export function headerPromptFor(
    prompts: readonly PlacedPrompt[],
    viewportTop: number,
): number {
    if (!Number.isFinite(viewportTop)) return 0;
    let found = 0;
    for (const p of prompts) {
        if (p.line <= viewportTop) found = p.ordinal;
        else break;
    }
    return found;
}

export interface HeaderControls {
    hasPrev: boolean;
    hasNext: boolean;
}

export function headerControlsFor(
    prompts: readonly PlacedPrompt[],
    currentOrdinal: number,
    maxViewportTop: number,
): HeaderControls {
    if (currentOrdinal === 0) return { hasPrev: false, hasNext: false };
    const hasPrev = prompts.some((p) => p.ordinal === currentOrdinal - 1);
    const next = prompts.find((p) => p.ordinal === currentOrdinal + 1);
    const hasNext = next !== undefined && Number.isFinite(maxViewportTop)
        && next.line <= maxViewportTop;
    return { hasPrev, hasNext };
}

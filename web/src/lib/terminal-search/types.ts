
export interface DisposableLike {
    dispose?(): void;
}

export interface MarkerLike {
    line?: number;
    isDisposed?: boolean;
    dispose?(): void;
}

export interface BufferLike {
    type?: string;
    baseY?: number;
    cursorY?: number;
    viewportY?: number;
    length?: number;
}

export interface TermLike {
    cols?: number;
    rows?: number;
    buffer?: { active?: BufferLike };
    registerMarker?(offset: number): MarkerLike | null | undefined;
    scrollToLine?(line: number): void;
    focus?(): void;
    clearSelection?(): void;
    onWriteParsed?(cb: () => void): DisposableLike;
    onScroll?(cb: () => void): DisposableLike;
}

export interface ScannedPrompt {
    ordinal: number;
    line: number;
    text: string;
    full: string;
    preview: string;
}

export interface RailPrompt extends ScannedPrompt {
    marker: MarkerLike | null;
    matches: boolean;
}

export interface Tick {
    ordinals: number[];
    y: number;
}

export interface PromptScanApi {
    scan(
        buffer: BufferLike,
        opts: {
            cols?: number;
            baseY?: number;
            rows?: number;
            isRule?: (text: string) => boolean;
            family?: string | null;
        },
    ): ScannedPrompt[];
    layoutTicks(
        prompts: Array<{ ordinal: number; line: number }>,
        bufferLength: number,
        railHeight: number,
    ): Tick[];
    currentOrdinalFor(
        prompts: Array<{ ordinal: number; line: number }>,
        viewportY: number,
    ): number;
}

export interface EngineResults {
    resultIndex?: number | null;
    resultCount?: number | null;
    limit?: number | null;
}

export interface SearchEngineApi {
    attach(term: TermLike): unknown;
    find(query: string, opts: Record<string, unknown>, dir: 'next' | 'prev'): unknown;
    next(): unknown;
    prev(): unknown;
    clear(): unknown;
    onResults(cb: (results: EngineResults) => void): () => void;
    predicate(query: string, opts?: Record<string, unknown>): (text: string) => boolean;
}

export type HistoryState = null | 'pending' | 'painted' | 'already' | 'unavailable';

export interface HistoryApi {
    ensureLoaded(
        term: TermLike,
        sessionId: string | null,
        controller?: unknown,
    ): Promise<{ loaded?: HistoryState }>;
}

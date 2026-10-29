import type { EngineResults, HistoryState } from './types';

const DEFAULT_LIMIT = 1000;

export interface CountState {
    history: HistoryState;
    query: string;
    results: EngineResults | null;
}

export function countLabel(state: CountState): string {
    if (state.history === 'pending') return 'loading history...';
    if (!state.query) {
        return state.history === 'unavailable' ? 'searching recent output only' : '';
    }
    const r = state.results;
    if (!r || r.resultCount === null || r.resultCount === undefined) return '';
    if (r.resultCount === 0) return 'no matches';
    const limit = r.limit || DEFAULT_LIMIT;
    if (r.resultCount >= limit) return `${limit}+`;
    const n = r.resultIndex === null || r.resultIndex === undefined ? 1 : r.resultIndex + 1;
    return `${n} of ${r.resultCount}`;
}

/* the prompts-only toggle */
export interface PromptCountState {
    prompts: Array<{ ordinal: number; matches: boolean }>;
    currentOrdinal: number;
}

export function promptCountLabel(state: PromptCountState): string {
    const list = state.prompts.filter((p) => p.matches);
    if (list.length === 0) return 'no prompts match';
    const at = list.findIndex((p) => p.ordinal === state.currentOrdinal);
    const k = at === -1 ? 0 : at + 1;
    return `${k} of ${list.length} prompts`;
}

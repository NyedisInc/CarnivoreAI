import type { Translate } from '../sessions/types';
import type { EngineResults, HistoryState } from './types';

const DEFAULT_LIMIT = 1000;

export interface CountState {
    history: HistoryState;
    query: string;
    results: EngineResults | null;
}

export function countLabel(state: CountState, t: Translate): string {
    if (state.history === 'pending') return t('search.count.loading');
    if (!state.query) {
        return state.history === 'unavailable' ? t('search.count.recent_only') : '';
    }
    const r = state.results;
    if (!r || r.resultCount === null || r.resultCount === undefined) return '';
    if (r.resultCount === 0) return t('search.count.none');
    const limit = r.limit || DEFAULT_LIMIT;
    if (r.resultCount >= limit) return t('search.count.capped', { limit: String(limit) });
    const n = r.resultIndex === null || r.resultIndex === undefined ? 1 : r.resultIndex + 1;
    return t('search.count.at', { n: String(n), count: String(r.resultCount) });
}

/* the prompts-only toggle */
export interface PromptCountState {
    prompts: Array<{ ordinal: number; matches: boolean }>;
    currentOrdinal: number;
}

export function promptCountLabel(state: PromptCountState, t: Translate): string {
    const list = state.prompts.filter((p) => p.matches);
    if (list.length === 0) return t('search.count.prompts_none');
    const at = list.findIndex((p) => p.ordinal === state.currentOrdinal);
    const k = at === -1 ? 0 : at + 1;
    return t('search.count.prompts_at', { k: String(k), n: String(list.length) });
}

import { groupedSearchApi, type DeepGroup, type DeepSearchApi } from '../deepsearch/deepsearch-api';
import { PROMPTS_SEARCH_PATH } from '../drawer-tabs/search-modes';

export const DEEP_MIN_CHARS = 3;
export const DEEP_DEBOUNCE_MS = 250;

export interface DeepRunner {
    query(text: string): void;
    cancel(): void;
}

export function createDeepRunner(onResult: (groups: DeepGroup[] | null) => void, api: DeepSearchApi = groupedSearchApi(PROMPTS_SEARCH_PATH)): DeepRunner {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let inflight: AbortController | null = null;
    const cancel = (): void => {
        if (timer) clearTimeout(timer);
        timer = null;
        inflight?.abort();
        inflight = null;
    };
    return {
        query(text) {
            cancel();
            const q = text.trim();
            if (q.length < DEEP_MIN_CHARS) {
                onResult([]);
                return;
            }
            onResult(null);
            timer = setTimeout(() => {
                timer = null;
                const ctl = new AbortController();
                inflight = ctl;
                api.search(q, 0, ctl.signal).then((answer) => {
                    if (!ctl.signal.aborted) onResult(answer.groups ?? []);
                }, (err: unknown) => {
                    if (ctl.signal.aborted) return;
                    console.warn('palette: conversation search failed', err);
                    onResult([]);
                });
            }, DEEP_DEBOUNCE_MS);
        },
        cancel,
    };
}

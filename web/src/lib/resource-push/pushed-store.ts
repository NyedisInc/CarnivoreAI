import { resourcePush } from './boot';
import { singleFlightWithRerun } from './single-flight';

export interface PushedStoreSpec<F> {
    topics: readonly string[];
    pollMs: number;
    read: (fetcher: F | undefined) => Promise<void>;
    onDetach?: () => void;
}

export interface PushedStore<F> {
    refresh: () => Promise<void>;
    attach: (fetcher?: F) => () => void;
    fetcher: () => F | undefined;
}

export function createPushedStore<F>(spec: PushedStoreSpec<F>): PushedStore<F> {
    let fetcherInUse: F | undefined;
    let attached = 0;
    let stop: (() => void) | null = null;
    const refresh = singleFlightWithRerun(() => spec.read(fetcherInUse));

    return {
        refresh,
        fetcher: () => fetcherInUse,
        attach(fetcher?: F): () => void {
            if (fetcher) fetcherInUse = fetcher;
            attached += 1;
            if (attached === 1) stop = resourcePush().pushOrPoll(() => void refresh(), spec.pollMs, spec.topics);
            void refresh();
            return () => {
                attached -= 1;
                if (attached === 0) {
                    stop?.();
                    stop = null;
                    fetcherInUse = undefined;
                    spec.onDetach?.();
                }
            };
        },
    };
}

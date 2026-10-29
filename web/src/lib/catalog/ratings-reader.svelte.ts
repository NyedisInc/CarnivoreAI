
import { reasonOf } from '../../../../client/js/labels/skill.js';
import type { CatalogHost } from './catalog';
import { ratingsView, type RatingsView } from './ratings';
import type { ItemRatings } from './types';
import type { Translate } from '../sessions/types';

export interface RatingsReader {
    readonly view: RatingsView;
    readonly loading: boolean;
    readonly failure: string | null;
    reload(): void;
}

export function createRatingsReader(
    getItemId: () => string | null,
    host: Pick<CatalogHost, 'itemRatings'>,
    t: Translate,
): RatingsReader {
    let body = $state<ItemRatings | null>(null);
    let loading = $state(false);
    let failure = $state<string | null>(null);
    let reloads = $state(0);
    let bodyFor: string | null = null;
    const view = $derived(ratingsView(body));

    $effect(() => {
        const id = getItemId();
        void reloads;
        if (id !== bodyFor) {
            body = null;
            bodyFor = id;
        }
        failure = null;
        if (!id) return;
        let cancelled = false;
        loading = true;
        void (async () => {
            try {
                const answer = await host.itemRatings(id);
                if (!cancelled) body = answer;
            } catch (error) {
                if (!cancelled) failure = reasonOf(error, t);
            } finally {
                if (!cancelled) loading = false;
            }
        })();
        return () => {
            cancelled = true;
        };
    });

    return {
        get view() { return view; },
        get loading() { return loading; },
        get failure() { return failure; },
        reload() { reloads += 1; },
    };
}

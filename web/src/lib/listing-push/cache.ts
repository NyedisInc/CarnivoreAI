import { readCached, throttledWriter, type ThrottledWriter } from '../data-cache/cache';
import type { ListingStore, Snapshot } from './store';

export const LISTING_CACHE_KEY = 'listing';

export const HYDRATE_WAIT_MS = 250;

export function hydrateAndPersist(store: ListingStore): Promise<void> {
    const writer: ThrottledWriter = throttledWriter<Snapshot>(LISTING_CACHE_KEY, () => store.snapshot());
    store.onChange(() => { if (store.isLive()) writer.schedule(); });
    const read = readCached<Snapshot>(LISTING_CACHE_KEY).then((snap) => store.hydrate(snap));
    const give = new Promise<void>((resolve) => setTimeout(resolve, HYDRATE_WAIT_MS));
    return Promise.race([read, give]);
}

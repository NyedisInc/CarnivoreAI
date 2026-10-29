import { errorText } from '../../settings-page/panel-kit/error-text';
import { resourcePush } from '../../resource-push/boot';
import { EMPTY_SYNC, fetchSync, postSyncNow, putPeer, type Fetcher, type SyncBody } from './api';

export const sync = $state<{ body: SyncBody; known: boolean; problem: string; syncing: boolean }>({
    body: EMPTY_SYNC, known: false, problem: '', syncing: false,
});

export const SYNC_POLL_MS = 15000;

let fetcherInUse: Fetcher | undefined;
let inflight: Promise<void> | null = null;
let attached = 0;
let stop: (() => void) | null = null;

export function refresh(): Promise<void> {
    inflight ??= read().finally(() => { inflight = null; });
    return inflight;
}

async function read(): Promise<void> {
    try {
        sync.body = await fetchSync(fetcherInUse);
        sync.problem = '';
        sync.known = true;
    } catch (error) {
        sync.problem = errorText(error);
    }
}

export async function setPeer(key: string, enabled: boolean): Promise<void> {
    sync.problem = '';
    try {
        sync.body = await putPeer(key, enabled, fetcherInUse);
        sync.known = true;
    } catch (error) {
        const problem = errorText(error);
        await refresh();
        sync.problem = problem;
    }
}

export async function syncNow(): Promise<void> {
    sync.problem = '';
    sync.syncing = true;
    try {
        await postSyncNow(fetcherInUse);
    } catch (error) {
        sync.problem = errorText(error);
    } finally {
        sync.syncing = false;
    }
}

export function attach(fetcher?: Fetcher): () => void {
    if (fetcher) fetcherInUse = fetcher;
    attached += 1;
    if (attached === 1) stop = resourcePush().pushOrPoll(() => void refresh(), SYNC_POLL_MS, ['notification_settings']);
    void refresh();
    return () => {
        attached -= 1;
        if (attached === 0) {
            stop?.();
            stop = null;
            fetcherInUse = undefined;
            sync.syncing = false;
        }
    };
}

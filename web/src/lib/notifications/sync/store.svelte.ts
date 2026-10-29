import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { EMPTY_SYNC, fetchSync, postSyncNow, putPeer, type Fetcher, type SyncBody } from './api';

export const sync = $state<{ body: SyncBody; known: boolean; problem: string; syncing: boolean }>({
    body: EMPTY_SYNC, known: false, problem: '', syncing: false,
});

export const SYNC_POLL_MS = 15000;

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        sync.body = await fetchSync(fetcher);
        sync.problem = '';
        sync.known = true;
    } catch (error) {
        sync.problem = errorText(error);
    }
}

export async function setPeer(key: string, enabled: boolean): Promise<void> {
    sync.problem = '';
    try {
        sync.body = await putPeer(key, enabled, store.fetcher());
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
        await postSyncNow(store.fetcher());
    } catch (error) {
        sync.problem = errorText(error);
    } finally {
        sync.syncing = false;
    }
}

const store = createPushedStore<Fetcher>({
    topics: ['notification_settings'], pollMs: SYNC_POLL_MS, read, onDetach: () => { sync.syncing = false; },
});
export const { refresh, attach } = store;

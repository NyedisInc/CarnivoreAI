import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { EMPTY_SETTINGS, fetchRegistry, fetchRouting, putPaused, type Family, type Fetcher, type RoutingSettings, type TypeRow } from './api';

export const matrix = $state<{ families: Family[]; types: TypeRow[]; aliases: Record<string, string>; settings: RoutingSettings; loaded: boolean; problem: string }>({
    families: [], types: [], aliases: {}, settings: EMPTY_SETTINGS, loaded: false, problem: '',
});

export const MATRIX_POLL_MS = 15000;

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        if (matrix.types.length === 0) {
            const registry = await fetchRegistry(fetcher);
            matrix.families = registry.families;
            matrix.types = registry.types;
            matrix.aliases = registry.aliases;
        }
        matrix.settings = await fetchRouting(fetcher);
        matrix.problem = '';
        matrix.loaded = true;
    } catch (error) {
        matrix.problem = errorText(error);
    }
}

async function act(work: () => Promise<void>): Promise<void> {
    matrix.problem = '';
    try {
        await work();
    } catch (error) {
        const problem = errorText(error);
        await refresh();
        matrix.problem = problem;
    }
}

export const setPaused = (paused: boolean): Promise<void> =>
    act(async () => {
        await putPaused(paused, store.fetcher());
        matrix.settings = { ...matrix.settings, paused };
    });

const store = createPushedStore<Fetcher>({ topics: ['notification_settings'], pollMs: MATRIX_POLL_MS, read });
export const { refresh, attach } = store;

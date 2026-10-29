import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { EMPTY_SETTINGS, fetchRegistry, fetchRouting, putDefault, putPaused, putTick, resetTick, SCREEN, type Cell, type Family, type Fetcher, type RoutingSettings, type TypeRow } from './api';

export const matrix = $state<{ families: Family[]; types: TypeRow[]; settings: RoutingSettings; loaded: boolean; problem: string; localOnly: boolean }>({
    families: [], types: [], settings: EMPTY_SETTINGS, loaded: false, problem: '', localOnly: false,
});

export const MATRIX_POLL_MS = 15000;

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        if (matrix.types.length === 0) {
            const registry = await fetchRegistry(fetcher);
            matrix.families = registry.families;
            matrix.types = registry.types;
        }
        matrix.settings = await fetchRouting(fetcher);
        matrix.problem = '';
        matrix.loaded = true;
    } catch (error) {
        matrix.problem = errorText(error);
    }
}

function setCell(column: string, typeId: string, cell: Cell): void {
    const s = matrix.settings;
    if (column === SCREEN) matrix.settings = { ...s, screen: { ...s.screen, [typeId]: cell } };
    else matrix.settings = { ...s, ticks: { ...s.ticks, [column]: { ...(s.ticks[column] ?? {}), [typeId]: cell } } };
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

export const setTick = (column: string, typeId: string, value: boolean): Promise<void> =>
    act(async () => {
        const body = matrix.localOnly ? { column, type_id: typeId, value, scope: 'local' as const } : { column, type_id: typeId, value };
        setCell(column, typeId, (await putTick(body, store.fetcher())).cell);
    });

export const resetCell = (column: string, typeId: string): Promise<void> =>
    act(async () => {
        await resetTick(column, typeId, store.fetcher());
        await refresh();
    });

export const setDefault = (typeId: string, value: boolean): Promise<void> =>
    act(async () => {
        const answer = await putDefault(typeId, value, store.fetcher());
        matrix.settings = { ...matrix.settings, defaults: answer.defaults };
    });

export const setPaused = (paused: boolean): Promise<void> =>
    act(async () => {
        await putPaused(paused, store.fetcher());
        matrix.settings = { ...matrix.settings, paused };
    });

const store = createPushedStore<Fetcher>({ topics: ['notification_settings'], pollMs: MATRIX_POLL_MS, read });
export const { refresh, attach } = store;

import { errorText } from '../../settings-page/panel-kit/error-text';
import { resourcePush } from '../../resource-push/boot';
import { EMPTY_SETTINGS, fetchRegistry, fetchRouting, putDefault, putPaused, putTick, resetTick, SCREEN, type Cell, type Family, type Fetcher, type RoutingSettings, type TypeRow } from './api';

export const matrix = $state<{ families: Family[]; types: TypeRow[]; settings: RoutingSettings; loaded: boolean; problem: string; localOnly: boolean }>({
    families: [], types: [], settings: EMPTY_SETTINGS, loaded: false, problem: '', localOnly: false,
});

export const MATRIX_POLL_MS = 15000;

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
        if (matrix.types.length === 0) {
            const registry = await fetchRegistry(fetcherInUse);
            matrix.families = registry.families;
            matrix.types = registry.types;
        }
        matrix.settings = await fetchRouting(fetcherInUse);
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
        setCell(column, typeId, (await putTick(body, fetcherInUse)).cell);
    });

export const resetCell = (column: string, typeId: string): Promise<void> =>
    act(async () => {
        await resetTick(column, typeId, fetcherInUse);
        await refresh();
    });

export const setDefault = (typeId: string, value: boolean): Promise<void> =>
    act(async () => {
        const answer = await putDefault(typeId, value, fetcherInUse);
        matrix.settings = { ...matrix.settings, defaults: answer.defaults };
    });

export const setPaused = (paused: boolean): Promise<void> =>
    act(async () => {
        await putPaused(paused, fetcherInUse);
        matrix.settings = { ...matrix.settings, paused };
    });

export function attach(fetcher?: Fetcher): () => void {
    if (fetcher) fetcherInUse = fetcher;
    attached += 1;
    if (attached === 1) stop = resourcePush().pushOrPoll(() => void refresh(), MATRIX_POLL_MS, ['notification_settings']);
    void refresh();
    return () => {
        attached -= 1;
        if (attached === 0) {
            stop?.();
            stop = null;
            fetcherInUse = undefined;
        }
    };
}

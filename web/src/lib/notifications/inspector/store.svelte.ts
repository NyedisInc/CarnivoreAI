import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { fetchRoutes, fetchStyles, putMaster, putRoutes, putStyle, type Fetcher, type RoutesBody, type StylePatch, type StylesDoc, type Target } from './api';

export const inspector = $state<{ doc: StylesDoc; routes: RoutesBody | null; loaded: boolean; problem: string }>({
    doc: { styles: {}, sounds: [], urgencies: [] }, routes: null, loaded: false, problem: '',
});

export const INSPECTOR_POLL_MS = 15000;

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        const [doc, routes] = await Promise.all([fetchStyles(fetcher), fetchRoutes(fetcher)]);
        inspector.doc = doc;
        inspector.routes = routes;
        inspector.problem = '';
        inspector.loaded = true;
    } catch (error) {
        inspector.problem = errorText(error);
    }
}

const store = createPushedStore<Fetcher>({ topics: ['notification_settings'], pollMs: INSPECTOR_POLL_MS, read });
export const { refresh, attach } = store;

async function act(work: () => Promise<void>): Promise<void> {
    inspector.problem = '';
    try {
        await work();
    } catch (error) {
        const problem = errorText(error);
        await refresh();
        inspector.problem = problem;
    }
}

export const setStyle = (typeId: string, patch: StylePatch): Promise<void> =>
    act(async () => {
        const answer = await putStyle(typeId, patch, store.fetcher());
        if (answer?.styles) inspector.doc = { ...inspector.doc, styles: answer.styles };
    });

export const setStyles = async (typeIds: readonly string[], patch: StylePatch): Promise<void> => {
    for (const id of typeIds) await setStyle(id, patch);
};

export const setMaster = (typeIds: readonly string[], value: boolean): Promise<void> =>
    act(async () => {
        inspector.routes = await putMaster(typeIds, value, store.fetcher());
    });

export const setRoute = (typeIds: readonly string[], computer: string, target: Target, value: boolean): Promise<void> =>
    act(async () => {
        inspector.routes = await putRoutes({ type_ids: typeIds, computer, target, value }, store.fetcher());
    });

export { store as inspectorStore };

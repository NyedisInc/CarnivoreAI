import { errorText } from '../../settings-page/panel-kit/error-text';
import { createPushedStore } from '../../resource-push/pushed-store';
import { fetchStyles, putStyle, type Fetcher, type StylePatch, type StylesDoc } from './api';

export const inspector = $state<{ doc: StylesDoc; loaded: boolean; problem: string }>({
    doc: { styles: {}, sounds: [], urgencies: [] }, loaded: false, problem: '',
});

export const INSPECTOR_POLL_MS = 15000;

async function read(fetcher: Fetcher | undefined): Promise<void> {
    try {
        inspector.doc = await fetchStyles(fetcher);
        inspector.problem = '';
        inspector.loaded = true;
    } catch (error) {
        inspector.problem = errorText(error);
    }
}

const store = createPushedStore<Fetcher>({ topics: ['notification_settings'], pollMs: INSPECTOR_POLL_MS, read });
export const { refresh, attach } = store;

export async function setStyle(typeId: string, patch: StylePatch): Promise<void> {
    inspector.problem = '';
    try {
        const answer = await putStyle(typeId, patch, store.fetcher());
        if (answer?.styles) inspector.doc = { ...inspector.doc, styles: answer.styles };
    } catch (error) {
        const problem = errorText(error);
        await refresh();
        inspector.problem = problem;
    }
}

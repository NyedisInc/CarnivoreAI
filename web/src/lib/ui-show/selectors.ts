import { browsers } from '../browser/api.svelte';
import { openPages } from '../browser/pages.svelte';
import { selectBrowserItem } from '../browser/select-push.svelte';
import { showTaskManager } from '../task-manager-reveal/reveal';
import { openFiles } from '../open-files/api.svelte';
import { browserSessionsSearchHost } from '../sessions-search/host';
import { openLayout } from '../../opscenter/layouts/page.svelte';

export type ShowKind = 'session' | 'file' | 'browser' | 'board' | 'layout' | 'task_manager';

export interface ShowSelectors {
    session(id: string, tmuxSession: string): Promise<boolean>;
    file(id: string): Promise<boolean>;
    browser(id: string): Promise<boolean>;
    board(id: string): Promise<boolean>;
    layout(uuid: string): Promise<boolean>;
    taskManager(): Promise<boolean>;
}

async function selectRow(refreshes: Array<Promise<unknown>>, id: string): Promise<boolean> {
    for (const result of await Promise.allSettled(refreshes)) {
        if (result.status === 'rejected') console.warn('ui show: list refresh failed', result.reason);
    }
    return selectBrowserItem(id);
}

export function browserSelectors(): ShowSelectors {
    return {
        session: (id, tmux) => browserSessionsSearchHost().navigate(id, tmux),
        file: (id) => selectRow([openFiles.refresh(true)], id),
        browser: (id) => selectRow([browsers.refresh(true), openPages.refresh(true)], id),
        board: (id) => selectRow([openPages.refresh(true)], id),
        layout: async (uuid) => {
            await openLayout(uuid);
            return true;
        },
        taskManager: async () => (await showTaskManager()) !== 'missing',
    };
}

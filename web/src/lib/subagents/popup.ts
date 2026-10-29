import { mountPanel, unmountPanel } from '../mount';
import { hostDocument } from '../sessions/env';
import SubagentList from './SubagentList.svelte';

export const SUBAGENT_LIST_ID = 'subagent-list-popup';

export function closeSubagentList(): boolean {
    return unmountPanel(SUBAGENT_LIST_ID);
}

export function openSubagentList(anchor: HTMLElement, sessionId: string, name: string): boolean {
    const doc = hostDocument();
    if (!doc || !sessionId) return false;
    let host = doc.getElementById(SUBAGENT_LIST_ID);
    if (!host) {
        host = doc.createElement('div');
        host.id = SUBAGENT_LIST_ID;
        doc.body.appendChild(host);
    }
    const mounted = mountPanel(SUBAGENT_LIST_ID, SubagentList, {
        anchor,
        sessionId,
        name,
        onClose: () => void closeSubagentList(),
    });
    return mounted !== null;
}

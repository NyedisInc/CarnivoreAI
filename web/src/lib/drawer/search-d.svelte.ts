import type { DeepSearchController } from '../deepsearch/deepsearch.svelte';
import type { DeepGroup, DeepHit } from '../deepsearch/deepsearch-api';

export interface SearchActions {
    searchConversations(): void;
    clear(): void;
}

export const searchD = $state({
    controller: null as DeepSearchController | null,
    agentNames: [] as string[],
    cursor: 0,
    actions: null as SearchActions | null,
    folded: { agents: false, conversations: false },
});

export const TOP_CONVERSATIONS = 3;

export interface TopHit {
    group: DeepGroup;
    hit: DeepHit;
}

export function topHits(): TopHit[] {
    const c = searchD.controller;
    if (!c || c.phase !== 'done' || searchD.folded.conversations) return [];
    return c.groups.slice(0, TOP_CONVERSATIONS).flatMap((group) => (group.hits[0] ? [{ group, hit: group.hits[0] }] : []));
}

export function cursorSize(): number {
    return searchD.agentNames.length + topHits().length;
}

export function cursorTarget(): { kind: 'agent'; name: string } | { kind: 'hit'; top: TopHit } | null {
    const agents = searchD.agentNames.length;
    if (searchD.cursor < agents) return { kind: 'agent', name: searchD.agentNames[searchD.cursor] as string };
    const top = topHits()[searchD.cursor - agents];
    return top ? { kind: 'hit', top } : null;
}

export function moveCursor(delta: number): void {
    const n = cursorSize();
    if (n === 0) return;
    searchD.cursor = (searchD.cursor + delta + n) % n;
}

export function resetCursor(): void {
    searchD.cursor = 0;
}

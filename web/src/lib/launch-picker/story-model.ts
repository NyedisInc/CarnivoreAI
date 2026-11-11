import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';

export type ItemKind = 'project' | 'feature' | 'story';

export interface WorkItem {
    id: string;
    kind: string;
    parent_id: string | null;
    title: string;
    status?: string;
    sprint_state?: string;
    updated_at?: string;
}

export interface WorkItemList { enabled: boolean; state: string; items: WorkItem[] }

export interface Candidate { id: string; title: string; kind: string }

export interface StoryGroup { key: 'active' | 'recent' | 'rest'; items: WorkItem[] }

export const RECENT_COUNT = 5;

type Fetcher = typeof authFetch;

export function createStoryApi(f: Fetcher = authFetch) {
    return {
        list: () => f<WorkItemList>('/argent/work-items'),
        create: (kind: ItemKind, parentId: string | null, title: string) => f<WorkItem>('/argent/work-items', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, parent_id: parentId, title }),
        }),
    };
}
export type StoryApi = ReturnType<typeof createStoryApi>;

function byNewest(a: WorkItem, b: WorkItem): number {
    return (b.updated_at ?? '').localeCompare(a.updated_at ?? '') || a.title.localeCompare(b.title);
}

export function groupItems(items: readonly WorkItem[], query: string): StoryGroup[] {
    const q = query.trim().toLowerCase();
    const kept = items.filter((i) => !q || i.title.toLowerCase().includes(q));
    const active = kept.filter((i) => i.sprint_state === 'active').sort(byNewest);
    const others = kept.filter((i) => i.sprint_state !== 'active').sort(byNewest);
    const recent = others.slice(0, RECENT_COUNT);
    const rest = others.slice(RECENT_COUNT).sort((a, b) => a.title.localeCompare(b.title));
    const groups: StoryGroup[] = [{ key: 'active', items: active }, { key: 'recent', items: recent }, { key: 'rest', items: rest }];
    return groups.filter((g) => g.items.length > 0);
}

export function rowVisible(list: WorkItemList | null): boolean {
    return !!list && list.enabled;
}

export function hasChoices(list: WorkItemList | null): boolean {
    return rowVisible(list) && list!.items.length > 0;
}

export function storyAnswer(picked: string, items: readonly WorkItem[]): string | null {
    return picked && items.some((i) => i.id === picked) ? picked : null;
}

export const PARENT_KIND: Record<ItemKind, ItemKind | null> = { project: null, feature: 'project', story: 'feature' };

export function candidatesOf(err: unknown): Candidate[] {
    if (!(err instanceof ApiError) || err.status !== 409) return [];
    const detail = (err.payload as { detail?: { details?: { candidates?: unknown } } } | null)?.detail;
    const raw = detail?.details?.candidates;
    if (!Array.isArray(raw)) return [];
    return raw.filter((c): c is Candidate => !!c && typeof c.id === 'string' && typeof c.title === 'string')
        .map((c) => ({ id: c.id, title: c.title, kind: typeof c.kind === 'string' ? c.kind : '' }));
}

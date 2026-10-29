import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { repaintDrawer } from '../browser/drawer-repaint';

export const ROW_LOOKS_TOPIC = 'row_looks';

export const ROW_LOOKS_POLL_MS = 5000;

export const ROW_COLORS = [
    'orange', 'green', 'cyan', 'yellow', 'coral', 'violet', 'green-bright', 'yellow-bright',
] as const;

export const ROW_ICONS = [
    'docs', 'files', 'folder', 'code', 'terminal', 'globe', 'link', 'bookmark', 'star', 'bolt', 'rocket', 'chart',
    'database', 'cpu', 'lab', 'bell', 'eye', 'pencil', 'lock', 'info', 'question', 'spark', 'cube', 'radar', 'activity',
    'gear', 'swarm', 'bot', 'pin', 'skull', 'crown', 'image', 'chat', 'inbox-tray',
] as const;

export interface RowLook {
    color: string | null;
    icon: string | null;
}

export const rowLooks: Resource<Record<string, RowLook>> = resource<Record<string, RowLook>>(
    async () => (await authFetch<{ looks: Record<string, RowLook> }>('/sidebar/row-looks')).looks,
    {
        intervalMs: ROW_LOOKS_POLL_MS, name: 'row_looks', demo: () => ({}),
        topics: [ROW_LOOKS_TOPIC], afterPush: () => repaintDrawer(),
    },
);

export function colorValue(color: string | null | undefined): string | null {
    return color && (ROW_COLORS as readonly string[]).includes(color) ? `var(--oc-${color})` : null;
}

export function isRowIcon(icon: string | null | undefined): icon is string {
    return !!icon && (ROW_ICONS as readonly string[]).includes(icon);
}

export function stampLooks(rows: Array<{ kind?: unknown; browser_id?: unknown; [field: string]: unknown }>, looks: Record<string, RowLook> | null | undefined): void {
    if (!looks) return;
    for (const row of rows) {
        if (row.kind !== 'browser' || row.browser_id == null) continue;
        const look = looks[String(row.browser_id)];
        if (look && (look.color || look.icon)) row.look = { color: look.color ?? null, icon: look.icon ?? null };
    }
}

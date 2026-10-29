import { isLocked } from '../carnivore-account/account-store.svelte';
import { surfacesOf } from './registry';
import type { PluginContext, SessionCardRow } from './types';

export interface SessionCardMenuItem {
    readonly id: string;
    readonly shortcut: string;
    readonly label: string;
    readonly order: number;
    readonly locked: boolean;
    readonly feature?: string;
}

/* a session on a paired Mac (issue #163, P8b) */
const LOCAL_ONLY_ACTIONS: ReadonlySet<string> = new Set(['share-read-only', 'huddle-session-nudge', 'huddle-project-lead']);

const SESSION_KEYED_ACTIONS: ReadonlySet<string> = new Set(['huddle-session-nudge', 'huddle-project-lead']);

function refusedForPeer(id: string, row: SessionCardRow, hidden?: (row: SessionCardRow) => boolean): boolean {
    if (hidden?.(row)) return true;
    if (SESSION_KEYED_ACTIONS.has(id) && !row.sessionUuid) return true;
    return LOCAL_ONLY_ACTIONS.has(id) && typeof row.hostKey === 'string' && row.hostKey.startsWith('peer-');
}

export function sessionCardMenuItems(
    row: SessionCardRow,
    context: PluginContext,
): SessionCardMenuItem[] {
    return surfacesOf('session-card-action')
        .filter((c) => c.enabled(context) && !refusedForPeer(c.id, row, c.payload.hidden))
        .map((c) => ({
            id: c.id,
            shortcut: c.payload.shortcut,
            label: c.payload.label(row),
            order: c.order ?? 0,
            locked: c.feature !== undefined && isLocked(c.feature),
            ...(c.feature !== undefined ? { feature: c.feature } : {}),
        }));
}

export async function runSessionCardAction(
    id: string,
    row: SessionCardRow,
    context: PluginContext,
): Promise<boolean> {
    const found = surfacesOf('session-card-action').find((c) => c.id === id);
    if (!found) return false;
    if (!found.enabled(context) || refusedForPeer(id, row, found.payload.hidden)) return false;
    await found.payload.run(row, context);
    return true;
}

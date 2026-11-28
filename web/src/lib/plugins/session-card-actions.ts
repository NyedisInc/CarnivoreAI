import { isLocked } from '../carnivore-account/account-store.svelte';
import { surfacesOf } from './registry';
import { resolveActiveSlots, runSlotDescriptorAction } from './slot-actions';
import type { PluginContext, SessionCardAction, SessionCardRow } from './types';

export interface SessionCardMenuItem {
    readonly id: string;
    readonly label: string;
    readonly order: number;
    readonly locked: boolean;
    readonly feature?: string;
    readonly keyless?: boolean;
    readonly disabled?: boolean;
    readonly danger?: boolean;
    readonly reason?: string;
}

const SLOT_ACTION_PREFIX = 'cplug-slot:';
const DEFAULT_SLOT_ROW_ORDER = 650;

function slotActionItemId(pluginId: string, entryId: string): string {
    return `${SLOT_ACTION_PREFIX}${encodeURIComponent(pluginId)}:${encodeURIComponent(entryId)}`;
}

function parseSlotActionItemId(id: string): { pluginId: string; entryId: string } | null {
    if (!id.startsWith(SLOT_ACTION_PREFIX)) return null;
    const rest = id.slice(SLOT_ACTION_PREFIX.length);
    const sep = rest.indexOf(':');
    if (sep <= 0) return null;
    try {
        return {
            pluginId: decodeURIComponent(rest.slice(0, sep)),
            entryId: decodeURIComponent(rest.slice(sep + 1)),
        };
    } catch {
        return null;
    }
}

function isSessionCardRow(row: SessionCardRow): boolean {
    return !row.kind || row.kind === 'session';
}

function refusedForPeer(row: SessionCardRow, action: SessionCardAction): boolean {
    if (action.hidden?.(row)) return true;
    if (action.requiresSessionUuid && !row.sessionUuid) return true;
    return Boolean(action.localOnly) && typeof row.hostKey === 'string' && row.hostKey.startsWith('peer-');
}

export function sessionCardMenuItems(
    row: SessionCardRow,
    context: PluginContext,
): SessionCardMenuItem[] {
    const builtin: SessionCardMenuItem[] = surfacesOf('session-card-action')
        .filter((c) => c.enabled(context) && !refusedForPeer(row, c.payload))
        .map((c) => ({
            id: c.id,
            label: c.payload.label(row),
            order: c.order ?? 0,
            locked: c.feature !== undefined && isLocked(c.feature),
            ...(c.feature !== undefined ? { feature: c.feature } : {}),
        }));
    if (!isSessionCardRow(row)) return builtin;

    const slotItems: SessionCardMenuItem[] = [];
    for (const valid of resolveActiveSlots('session.row_actions')) {
        if (valid.kind !== 'descriptor' || !valid.action) continue;
        const reason = valid.tooltip || (valid.disabled ? 'Unavailable' : undefined);
        slotItems.push({
            id: slotActionItemId(valid.entry.plugin_id, valid.id),
            label: valid.label,
            order: valid.order ?? valid.priority ?? DEFAULT_SLOT_ROW_ORDER,
            locked: false,
            keyless: true,
            ...(valid.disabled ? { disabled: true } : {}),
            ...(valid.tone === 'danger' ? { danger: true } : {}),
            ...(reason ? { reason } : {}),
        });
    }
    return slotItems.length ? [...builtin, ...slotItems] : builtin;
}

export async function runSessionCardAction(
    id: string,
    row: SessionCardRow,
    context: PluginContext,
): Promise<boolean> {
    const found = surfacesOf('session-card-action').find((c) => c.id === id);
    if (found) {
        if (!found.enabled(context) || refusedForPeer(row, found.payload)) return false;
        await found.payload.run(row, context);
        return true;
    }

    const parsed = parseSlotActionItemId(id);
    if (!parsed || !isSessionCardRow(row)) return false;
    const match = resolveActiveSlots('session.row_actions').find(
        (valid) =>
            valid.kind === 'descriptor' &&
            valid.entry.plugin_id === parsed.pluginId &&
            valid.id === parsed.entryId &&
            !valid.disabled &&
            valid.action !== null,
    );
    if (!match || match.kind !== 'descriptor' || !match.action) return false;
    const sessionRef = row.sessionUuid || row.sessionId || row.name || null;
    try {
        const res = await runSlotDescriptorAction(parsed.pluginId, match.action, {
            sessionRef,
            confirm: match.confirm,
            title: match.label,
            tone: match.tone,
        });
        if (res !== false) await context.refresh();
    } catch (err) {
        console.error('[session-card-actions] slot action failed:', parsed.pluginId, parsed.entryId, err);
    }
    return true;
}

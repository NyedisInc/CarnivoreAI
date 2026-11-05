import type { DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';
import { depthOf } from './share-relay';

export interface ViewAction {
    readonly id: string;
    readonly label: string;
    readonly kind: 'action' | 'choice' | 'switch';
    readonly on?: boolean;
    readonly blocked?: string;
    readonly group?: string;
}

export const MAX_ACTIONS = 12;
export const MAX_ACTIONS_BYTES = 4096;
export const MAX_ACTIONS_DEPTH = 3;
export const MAX_LABEL_CHARS = 40;
export const MAX_BLOCKED_CHARS = 60;
export const MAX_ACTION_LISTS = 10;
export const ACTIONS_WINDOW_MS = 1000;
export const VIEW_ACTION_PREFIX = 'view:';
export const VIEW_GROUP_PREFIX = 'plugin:';
const DEFAULT_GROUP = 'main';

const ID_PATTERN = /^[a-z][a-z0-9_-]{0,15}(:[a-z][a-z0-9_-]{0,15})?$/;
const GROUP_PATTERN = /^[a-z][a-z0-9-]{0,15}$/;
// eslint-disable-next-line no-control-regex -- the point is to refuse control characters
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;

export type ActionsError = 'invalid_actions' | 'too_large';

function cleanText(value: unknown, max: number): string | null {
    if (typeof value !== 'string') return null;
    const text = value.trim();
    return text.length >= 1 && text.length <= max && !CONTROL.test(text) ? text : null;
}

function cleanOne(raw: unknown): ViewAction | null {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
    const a = raw as Record<string, unknown>;
    const label = cleanText(a.label, MAX_LABEL_CHARS);
    if (typeof a.id !== 'string' || !ID_PATTERN.test(a.id) || label === null) return null;
    const kind = a.kind ?? 'action';
    if (kind !== 'action' && kind !== 'choice' && kind !== 'switch') return null;
    if (kind === 'action' ? a.on !== undefined : typeof a.on !== 'boolean') return null;
    const blocked = a.blocked === undefined ? undefined : cleanText(a.blocked, MAX_BLOCKED_CHARS);
    if (blocked === null) return null;
    if (a.group !== undefined && (typeof a.group !== 'string' || !GROUP_PATTERN.test(a.group))) return null;
    return { id: a.id, label, kind, ...(kind === 'action' ? {} : { on: a.on as boolean }), ...(blocked === undefined ? {} : { blocked }), ...(a.group === undefined ? {} : { group: a.group as string }) };
}

export function cleanActions(message: Record<string, unknown>): { ok: true; actions: ViewAction[] } | { ok: false; error: ActionsError } {
    let text: string | undefined;
    try {
        text = JSON.stringify(message);
    } catch {
        return { ok: false, error: 'invalid_actions' };
    }
    if (text === undefined || new TextEncoder().encode(text).length > MAX_ACTIONS_BYTES || depthOf(message) > MAX_ACTIONS_DEPTH) return { ok: false, error: 'too_large' };
    const list = message.actions;
    if (!Array.isArray(list)) return { ok: false, error: 'invalid_actions' };
    if (list.length > MAX_ACTIONS) return { ok: false, error: 'too_large' };
    const actions: ViewAction[] = [];
    for (const raw of list) {
        const one = cleanOne(raw);
        if (!one || actions.some((seen) => seen.id === one.id)) return { ok: false, error: 'invalid_actions' };
        actions.push(one);
    }
    return { ok: true, actions };
}

export function declaredViewActions(actions: readonly ViewAction[], send: (id: string, on?: boolean) => void): DeclaredAction[] {
    return actions.map((a) => ({
        id: VIEW_ACTION_PREFIX + a.id,
        label: a.label,
        keyless: true,
        ...(a.kind === 'action' ? {} : { checked: a.on === true }),
        ...(a.kind === 'switch' ? { toggle: true } : {}),
        ...(a.blocked ? { blocked: a.blocked } : {}),
        group: VIEW_GROUP_PREFIX + (a.group ?? DEFAULT_GROUP),
        run: () => send(a.id, a.kind === 'switch' ? a.on !== true : a.kind === 'choice' ? true : undefined),
    }));
}

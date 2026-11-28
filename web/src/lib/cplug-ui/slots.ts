import type { authFetch } from '../../opscenter/api/auth.svelte';
import { isWidgetId } from '../../popout/popout';
import { canonicalSlotName, SLOT_ALIASES, type SlotContribution } from '../plugins/store.svelte';
import { callOwnerAct, callViewTool } from './api';
import {
    MAX_BYTES,
    MAX_LABEL,
    MAX_TEXT,
    STATUSES,
    TONES,
    hasDisallowedScheme,
    hasInvisibleChar,
    hasSecretShape,
    isSafeDisplayText,
    jsonSize,
    sanitizeSlotJsonValue,
    sanitizeSlotPayload,
    validateDocument,
    type Declared,
    type Tone,
} from './validate';

export { SLOT_ALIASES };

export function canonicalSlot(slot: string): string {
    return canonicalSlotName(slot);
}

export interface SlotDeclared extends Declared {
    readonly macros?: readonly string[];
}

export type SlotAction =
    | { readonly kind: 'route'; readonly route: string; readonly payload?: Record<string, unknown> }
    | { readonly kind: 'tool'; readonly tool: string; readonly payload?: Record<string, unknown> }
    | { readonly kind: 'macro'; readonly macro: string; readonly payload?: Record<string, unknown> }
    | { readonly kind: 'href'; readonly href: string; readonly external: boolean };

export type ValidSlotEntry =
    | {
          readonly kind: 'document';
          readonly entry: SlotContribution;
          readonly document: unknown;
          readonly id: string;
          readonly label: string;
          readonly title: string;
          readonly order: number | null;
          readonly priority: number | null;
      }
    | {
          readonly kind: 'descriptor';
          readonly entry: SlotContribution;
          readonly id: string;
          readonly label: string;
          readonly title: string | null;
          readonly subtitle: string | null;
          readonly description: string | null;
          readonly tooltip: string | null;
          readonly icon: string | null;
          readonly shortcut: string | null;
          readonly confirm: string | null;
          readonly badge: string | null;
          readonly tone: Tone | null;
          readonly status: string | null;
          readonly disabled: boolean;
          readonly order: number | null;
          readonly priority: number | null;
          readonly action: SlotAction | null;
      };

const ROUTE_OR_MACRO_RE = /^[a-z][a-z0-9_-]{0,39}$/;

const SLOT_LABEL_KEYS: ReadonlySet<string> = new Set([
    'id',
    'label',
    'title',
    'subtitle',
    'tooltip',
    'icon',
    'shortcut',
    'chord',
    'confirm',
    'badge',
    'command',
    'surface',
    'view',
    'panel',
    'position',
    'group',
    'category',
    'variant',
    'kind',
    'tab',
]);

const SLOT_ENTRY_KEYS: ReadonlySet<string> = new Set([
    ...SLOT_LABEL_KEYS,
    'widget',
    'description',
    'tone',
    'status',
    'disabled',
    'order',
    'priority',
    'width',
    'height',
    'route',
    'tool',
    'macro',
    'action',
    'href',
    'payload',
    'props',
    'data',
    'when',
    'popout',
    'document',
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function safeSlotHref(raw: unknown): { readonly href: string; readonly external: boolean } | null {
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    if (!trimmed || trimmed.length > MAX_TEXT) return null;
    if (hasInvisibleChar(raw) || hasSecretShape(raw)) return null;
    if (trimmed.startsWith('/')) {
        if (trimmed.startsWith('//') || hasDisallowedScheme(trimmed)) return null;
        return { href: trimmed, external: false };
    }
    if (!/^https?:\/\//i.test(trimmed) || /^https?:\/\/\//i.test(trimmed)) return null;
    try {
        const parsed = new URL(trimmed);
        const scheme = parsed.protocol.toLowerCase();
        if ((scheme === 'http:' || scheme === 'https:') && parsed.host) {
            return { href: trimmed, external: true };
        }
        return null;
    } catch {
        return null;
    }
}

function readNumOpt(raw: Record<string, unknown>, key: string): { ok: true; value: number | null } | { ok: false } {
    if (!(key in raw)) return { ok: true, value: null };
    const val = raw[key];
    if (typeof val !== 'number' || !Number.isFinite(val)) return { ok: false };
    return { ok: true, value: val };
}

function readStrOpt(
    raw: Record<string, unknown>,
    key: string,
    limit = MAX_LABEL,
    allowNewlines = false,
): { ok: true; value: string | null } | { ok: false } {
    if (!(key in raw)) return { ok: true, value: null };
    if (!isSafeDisplayText(raw[key], limit, allowNewlines)) return { ok: false };
    return { ok: true, value: raw[key] };
}

function resolveAction(
    raw: Record<string, unknown>,
    declared: SlotDeclared,
): { ok: true; action: SlotAction | null } | { ok: false } {
    let payload: Record<string, unknown> | undefined;
    if ('payload' in raw) {
        const cleanPayload = sanitizeSlotPayload(raw.payload);
        if (!cleanPayload) return { ok: false };
        payload = cleanPayload;
    }

    let actionChoice: SlotAction | null = null;
    if ('action' in raw) {
        const act = raw.action;
        if (isPlainObject(act)) {
            const call = act.call;
            if (call !== 'route' && call !== 'tool') return { ok: false };
            const field = call === 'route' ? 'route' : 'name';
            if (Object.keys(act).some((k) => k !== 'call' && k !== field && k !== 'payload')) return { ok: false };
            let actPayload = payload;
            if ('payload' in act) {
                const cleanActPayload = sanitizeSlotPayload(act.payload);
                if (!cleanActPayload) return { ok: false };
                actPayload = cleanActPayload;
            }
            if (call === 'route') {
                const route = act.route;
                if (typeof route !== 'string' || !declared.routes.includes(route)) return { ok: false };
                actionChoice = { kind: 'route', route, ...(actPayload ? { payload: actPayload } : {}) };
            } else {
                const tool = act.name;
                if (typeof tool !== 'string' || !declared.tools.includes(tool)) return { ok: false };
                actionChoice = { kind: 'tool', tool, ...(actPayload ? { payload: actPayload } : {}) };
            }
        } else {
            if (typeof act !== 'string' || !isSafeDisplayText(act, MAX_LABEL)) return { ok: false };
            if (!declared.routes.includes(act)) return { ok: false };
            actionChoice = { kind: 'route', route: act, ...(payload ? { payload } : {}) };
        }
    }

    let routeChoice: SlotAction | null = null;
    if ('route' in raw) {
        const route = raw.route;
        if (typeof route !== 'string' || !declared.routes.includes(route)) return { ok: false };
        routeChoice = { kind: 'route', route, ...(payload ? { payload } : {}) };
    }

    let toolChoice: SlotAction | null = null;
    if ('tool' in raw) {
        const tool = raw.tool;
        if (typeof tool !== 'string' || !declared.tools.includes(tool)) return { ok: false };
        toolChoice = { kind: 'tool', tool, ...(payload ? { payload } : {}) };
    }

    let macroChoice: SlotAction | null = null;
    if ('macro' in raw) {
        const macro = raw.macro;
        if (typeof macro !== 'string' || !isSafeDisplayText(macro, MAX_LABEL) || !ROUTE_OR_MACRO_RE.test(macro)) {
            return { ok: false };
        }
        if (declared.macros && !declared.macros.includes(macro)) return { ok: false };
        macroChoice = { kind: 'macro', macro, ...(payload ? { payload } : {}) };
    }

    let hrefChoice: SlotAction | null = null;
    if ('href' in raw) {
        const safeHref = safeSlotHref(raw.href);
        if (!safeHref) return { ok: false };
        hrefChoice = { kind: 'href', href: safeHref.href, external: safeHref.external };
    }

    return { ok: true, action: actionChoice ?? routeChoice ?? toolChoice ?? macroChoice ?? hrefChoice };
}

export function validateSlotEntry(
    entry: SlotContribution,
    declared: SlotDeclared = { routes: [], tools: [] },
): ValidSlotEntry | null {
    if (!entry || typeof entry.plugin_id !== 'string' || !isPlainObject(entry.item)) return null;
    const item = entry.item;
    try {
        if (jsonSize(item) > MAX_BYTES) return null;
    } catch {
        return null;
    }

    if ('schema' in item && 'root' in item) {
        const verdict = validateDocument(item, { routes: declared.routes, tools: declared.tools });
        if (!verdict.ok) return null;
        return {
            kind: 'document',
            entry,
            document: verdict.doc,
            id: entry.plugin_id,
            label: entry.plugin_id,
            title: entry.plugin_id,
            order: null,
            priority: null,
        };
    }

    for (const key of Object.keys(item)) {
        if (!SLOT_ENTRY_KEYS.has(key)) return null;
    }

    for (const key of SLOT_LABEL_KEYS) {
        if (key in item && !isSafeDisplayText(item[key], MAX_LABEL)) return null;
    }

    if ('widget' in item) {
        const w = item.widget;
        if (
            typeof w !== 'string' ||
            w.length === 0 ||
            w.length > MAX_LABEL ||
            hasInvisibleChar(w) ||
            hasSecretShape(w) ||
            !isWidgetId(w)
        ) {
            return null;
        }
    }

    const description = readStrOpt(item, 'description', MAX_TEXT, true);
    if (!description.ok) return null;

    let tone: Tone | null = null;
    if ('tone' in item) {
        if (typeof item.tone !== 'string' || !TONES.has(item.tone)) return null;
        tone = item.tone as Tone;
    }

    let status: string | null = null;
    if ('status' in item) {
        if (typeof item.status !== 'string' || !STATUSES.has(item.status)) return null;
        status = item.status;
    }

    let disabled = false;
    if ('disabled' in item) {
        if (typeof item.disabled !== 'boolean') return null;
        disabled = item.disabled;
    }

    const order = readNumOpt(item, 'order');
    const priority = readNumOpt(item, 'priority');
    const width = readNumOpt(item, 'width');
    const height = readNumOpt(item, 'height');
    if (!order.ok || !priority.ok || !width.ok || !height.ok) return null;

    for (const objKey of ['props', 'data', 'when', 'popout'] as const) {
        if (objKey in item && !sanitizeSlotJsonValue(item[objKey], objKey !== 'data').ok) return null;
    }

    const actionRes = resolveAction(item, declared);
    if (!actionRes.ok) return null;

    if ('document' in item) {
        const verdict = validateDocument(item.document, { routes: declared.routes, tools: declared.tools });
        if (!verdict.ok) return null;
        const id = (item.id as string | undefined) ?? entry.plugin_id;
        const label = (item.label as string | undefined) ?? (item.title as string | undefined) ?? id;
        const title = (item.title as string | undefined) ?? label;
        return {
            kind: 'document',
            entry,
            document: verdict.doc,
            id,
            label,
            title,
            order: order.value,
            priority: priority.value,
        };
    }

    const id = (item.id as string | undefined) ?? (item.command as string | undefined) ?? '';
    const label =
        (item.label as string | undefined) ??
        (item.title as string | undefined) ??
        (item.command as string | undefined) ??
        id;
    const title = (item.title as string | undefined) ?? null;
    const subtitle = (item.subtitle as string | undefined) ?? null;
    const tooltip = (item.tooltip as string | undefined) ?? null;
    const icon = (item.icon as string | undefined) ?? null;
    const shortcut = (item.shortcut as string | undefined) ?? (item.chord as string | undefined) ?? null;
    const confirm = (item.confirm as string | undefined) ?? null;
    const badge = (item.badge as string | undefined) ?? null;

    if (!label && !badge && !status) return null;

    return {
        kind: 'descriptor',
        entry,
        id: id || label,
        label,
        title,
        subtitle,
        description: description.value,
        tooltip,
        icon,
        shortcut,
        confirm,
        badge,
        tone,
        status,
        disabled,
        order: order.value,
        priority: priority.value,
        action: actionRes.action,
    };
}

export function sortSlotEntries(entries: readonly ValidSlotEntry[]): ValidSlotEntry[] {
    return [...entries].sort((a, b) => {
        const oa = a.order ?? a.priority ?? 0;
        const ob = b.order ?? b.priority ?? 0;
        if (oa !== ob) return oa - ob;
        const pid = a.entry.plugin_id.localeCompare(b.entry.plugin_id);
        if (pid !== 0) return pid;
        return (a.id || a.label).localeCompare(b.id || b.label);
    });
}

export async function executeSlotAction(
    pluginId: string,
    action: SlotAction,
    opts: { readonly sessionRef?: string | null; readonly fetcher?: typeof authFetch } = {},
): Promise<unknown> {
    if (action.kind === 'route') {
        return callOwnerAct(pluginId, action.route, action.payload, opts.sessionRef, opts.fetcher);
    }
    if (action.kind === 'macro') {
        return callOwnerAct(pluginId, action.macro, action.payload, opts.sessionRef, opts.fetcher);
    }
    if (action.kind === 'tool') {
        return callViewTool(pluginId, action.tool, action.payload ?? {}, opts.fetcher, opts.sessionRef);
    }
    return { href: action.href, external: action.external };
}

import { ACTIONS } from '../../../../client/js/keymap/actions.js';
import { formatChord, normalize, parse } from '../../../../client/js/keymap/chord.js';
import { refusal } from '../../../../client/js/keymap/protected.js';
import type { authFetch } from '../../opscenter/api/auth.svelte';
import type { AppChord } from '../app-keys/router';
import { confirmOk } from '../confirm-ok/confirm-ok';
import {
    canonicalSlot,
    executeSlotAction,
    sortSlotEntries,
    validateSlotEntry,
    type SlotAction,
    type SlotDeclared,
    type ValidSlotEntry,
} from '../cplug-ui/slots';
import { isSafeDisplayText, MAX_LABEL, type Tone } from '../cplug-ui/validate';
import { t } from '../i18n/index.svelte';
import type { KeyboardFamily } from '../keymap/keymap-view';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from './store.svelte';

const ROUTE_OR_MACRO_RE = /^[a-z][a-z0-9_-]{0,39}$/;

const CARET_KEYS: ReadonlySet<string> = new Set([
    'arrowup',
    'arrowdown',
    'arrowleft',
    'arrowright',
    'up',
    'down',
    'left',
    'right',
    'home',
    'end',
    'pageup',
    'pagedown',
]);

const DELETE_KEYS: ReadonlySet<string> = new Set(['backspace', 'delete']);

const FAMILY_MOD_ALIASES: Readonly<Record<string, string>> = {
    control: 'ctrl',
    ctrl: 'ctrl',
    alt: 'alt',
    option: 'alt',
    opt: 'alt',
    shift: 'shift',
    cmd: 'cmd',
    command: 'cmd',
    meta: 'cmd',
    super: 'cmd',
};

const SLOT_ROW_FALLBACK_KEYS: Readonly<Record<string, readonly string[]>> = {
    commands: ['commands'],
    chords: ['chords'],
    'session.row_actions': ['sessionRowActions', 'session_row_actions'],
    'session.badges': ['sessionBadges', 'session_badges'],
    'terminal.toolbar': ['terminalToolbar', 'terminal_toolbar'],
    'project.panels': ['projectPanels', 'project_panels'],
};

const SLOT_CONTRIB_ALIASES: Readonly<Record<string, readonly string[]>> = {
    'session.row_actions': ['session.row_actions', 'session_row_actions'],
    'session.badges': ['session.badges', 'session_badges'],
    'terminal.toolbar': ['terminal.toolbar', 'terminal_toolbar'],
    'project.panels': ['project.panels', 'project_panels'],
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isPluginRowActive(row: StoreCplugRow | undefined | null): row is StoreCplugRow {
    return Boolean(row && row.enabled === true && row.state === 'active' && !row.runtime_paused);
}

export function hasSlotConsent(row: StoreCplugRow | undefined | null, slotName: string): boolean {
    if (!row) return false;
    const raw = (row.granted_ui_slots ?? (row as { grantedUiSlots?: readonly string[] }).grantedUiSlots) as
        | readonly string[]
        | undefined;
    if (!Array.isArray(raw)) return false;
    const target = canonicalSlot(slotName);
    return raw.some((s) => typeof s === 'string' && canonicalSlot(s) === target);
}

export function declaredForRow(row: StoreCplugRow | undefined | null): SlotDeclared {
    return {
        routes: Array.isArray(row?.routes) ? row.routes : [],
        tools: Array.isArray(row?.declared_tools) ? row.declared_tools : [],
        ...(Array.isArray(row?.macros) ? { macros: row.macros } : {}),
    };
}

export function pluginDisplayName(pluginId: string, row: StoreCplugRow | undefined | null): string {
    if (row?.name) return row.name;
    if (row?.name_key) return t(row.name_key);
    return pluginId;
}

function rowUiContributeList(row: StoreCplugRow, slotName: string): Record<string, unknown>[] | null {
    const contrib = (row.ui_contribute ?? (row as { uiContribute?: Record<string, unknown> }).uiContribute) as
        | Record<string, unknown>
        | undefined;
    if (!isPlainObject(contrib)) return null;
    const canonical = canonicalSlot(slotName);
    const keys = SLOT_CONTRIB_ALIASES[canonical] ?? [canonical];
    const out: Record<string, unknown>[] = [];
    let found = false;
    for (const k of keys) {
        const list = contrib[k];
        if (Array.isArray(list)) {
            found = true;
            for (const item of list) {
                if (isPlainObject(item)) out.push(item);
            }
        }
    }
    return found ? out : null;
}

function fallbackRawItemsForSlot(row: StoreCplugRow, slotName: string): Record<string, unknown>[] {
    const contrib = rowUiContributeList(row, slotName);
    if (contrib) return contrib;
    const canonical = canonicalSlot(slotName);
    const keys = SLOT_ROW_FALLBACK_KEYS[canonical] ?? [];
    for (const key of keys) {
        const raw = (row as unknown as Record<string, unknown>)[key];
        if (Array.isArray(raw)) return raw.filter(isPlainObject);
    }
    return [];
}

export function resolveActiveSlots(slotName: string): ValidSlotEntry[] {
    const canonical = canonicalSlot(slotName);
    const storeSlots = pluginsStore.slotsFor(canonical);
    const out: ValidSlotEntry[] = [];

    if (pluginsStore.slotsRead || storeSlots.length > 0) {
        for (const entry of storeSlots) {
            const row = pluginsStore.rowOf(entry.plugin_id);
            if (!isPluginRowActive(row) || !hasSlotConsent(row, canonical)) {
                continue;
            }
            const valid = validateSlotEntry(entry, declaredForRow(row));
            if (valid) out.push(valid);
        }
        return sortSlotEntries(out);
    }

    for (const row of pluginsStore.rows) {
        if (!isPluginRowActive(row) || !hasSlotConsent(row, canonical)) continue;
        const installKey = typeof row.install_key === 'string' && row.install_key ? row.install_key : row.id;
        for (const item of fallbackRawItemsForSlot(row, canonical)) {
            const valid = validateSlotEntry(
                {
                    plugin_id: row.id,
                    install_key: installKey,
                    slot: canonical,
                    declared_slot: canonical,
                    item,
                },
                declaredForRow(row),
            );
            if (valid) out.push(valid);
        }
    }
    return sortSlotEntries(out);
}

export interface ResolvedPluginCommand {
    readonly key: string;
    readonly pluginId: string;
    readonly pluginName: string;
    readonly commandId: string;
    readonly label: string;
    readonly subtitle: string;
    readonly shortcut: string | null;
    readonly confirm: string | null;
    readonly tone: Tone | null;
    readonly order: number;
    readonly action: SlotAction;
}

function resolveMetaCommand(
    row: StoreCplugRow,
    raw: Record<string, unknown>,
): ResolvedPluginCommand | null {
    if ('disabled' in raw && typeof raw.disabled !== 'boolean') return null;
    if (raw.disabled === true) return null;
    const id = typeof raw.id === 'string' ? raw.id.trim() : '';
    if (!id || !ROUTE_OR_MACRO_RE.test(id)) return null;
    const rawLabel = typeof raw.title === 'string' ? raw.title : typeof raw.label === 'string' ? raw.label : id;
    if (!isSafeDisplayText(rawLabel, MAX_LABEL)) return null;

    let shortcut: string | null = null;
    if ('shortcut' in raw && raw.shortcut != null) {
        if (!isSafeDisplayText(raw.shortcut, MAX_LABEL)) return null;
        shortcut = raw.shortcut;
    }

    let confirm: string | null = null;
    if ('confirm' in raw && raw.confirm != null) {
        if (!isSafeDisplayText(raw.confirm, MAX_LABEL)) return null;
        confirm = raw.confirm;
    }

    let action: SlotAction | null = null;
    if ('steps' in raw && Array.isArray(raw.steps) && raw.steps.length > 0) {
        action = { kind: 'macro', macro: id };
    } else if ('route' in raw || 'tool' in raw || 'macro' in raw || 'href' in raw || 'action' in raw) {
        const installKey = typeof row.install_key === 'string' && row.install_key ? row.install_key : row.id;
        const valid = validateSlotEntry(
            {
                plugin_id: row.id,
                install_key: installKey,
                slot: 'commands',
                declared_slot: 'commands',
                item: raw,
            },
            declaredForRow(row),
        );
        if (!valid || valid.kind !== 'descriptor' || valid.disabled || !valid.action) return null;
        action = valid.action;
    } else if (Array.isArray(row.routes) && row.routes.includes(id)) {
        action = { kind: 'route', route: id };
    } else if (Array.isArray(row.declared_tools) && row.declared_tools.includes(id)) {
        action = { kind: 'tool', tool: id };
    }

    if (!action) return null;
    const pluginName = pluginDisplayName(row.id, row);
    return {
        key: `${row.id}:${id}`,
        pluginId: row.id,
        pluginName,
        commandId: id,
        label: rawLabel,
        subtitle: shortcut ? `${pluginName} · ${shortcut}` : pluginName,
        shortcut,
        confirm,
        tone: null,
        order: typeof raw.order === 'number' && Number.isFinite(raw.order) ? raw.order : 0,
        action,
    };
}

export function resolvePluginCommands(): ResolvedPluginCommand[] {
    const byKey = new Map<string, ResolvedPluginCommand>();

    for (const entry of resolveActiveSlots('commands')) {
        if (entry.kind !== 'descriptor' || entry.disabled || !entry.action) continue;
        const row = pluginsStore.rowOf(entry.entry.plugin_id);
        const pluginName = pluginDisplayName(entry.entry.plugin_id, row);
        const label = entry.title ?? entry.label;
        const key = `${entry.entry.plugin_id}:${entry.id}`;
        if (!byKey.has(key)) {
            byKey.set(key, {
                key,
                pluginId: entry.entry.plugin_id,
                pluginName,
                commandId: entry.id,
                label,
                subtitle: entry.shortcut ? `${pluginName} · ${entry.shortcut}` : pluginName,
                shortcut: entry.shortcut,
                confirm: entry.confirm,
                tone: entry.tone,
                order: entry.order ?? entry.priority ?? 0,
                action: entry.action,
            });
        }
    }

    for (const row of pluginsStore.rows) {
        if (!isPluginRowActive(row)) continue;
        const rawCommands = Array.isArray(row.commands) ? row.commands : [];
        if (rawCommands.length === 0) continue;
        const contribItems = rowUiContributeList(row, 'commands') ?? [];
        const contribIds = new Set(
            contribItems
                .map((c) => (typeof c.id === 'string' ? c.id : typeof c.command === 'string' ? c.command : ''))
                .filter(Boolean),
        );
        const hasConsent = hasSlotConsent(row, 'commands');

        for (const raw of rawCommands) {
            if (!isPlainObject(raw)) continue;
            const rawId = typeof raw.id === 'string' ? raw.id : typeof raw.command === 'string' ? raw.command : '';
            const isContrib = Boolean(rawId && contribIds.has(rawId));
            if (isContrib) {
                if (!hasConsent) continue;
                const installKey = typeof row.install_key === 'string' && row.install_key ? row.install_key : row.id;
                const valid = validateSlotEntry(
                    {
                        plugin_id: row.id,
                        install_key: installKey,
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: raw,
                    },
                    declaredForRow(row),
                );
                if (!valid || valid.kind !== 'descriptor' || valid.disabled || !valid.action) continue;
                const pluginName = pluginDisplayName(row.id, row);
                const label = valid.title ?? valid.label;
                const key = `${row.id}:${valid.id}`;
                if (!byKey.has(key)) {
                    byKey.set(key, {
                        key,
                        pluginId: row.id,
                        pluginName,
                        commandId: valid.id,
                        label,
                        subtitle: valid.shortcut ? `${pluginName} · ${valid.shortcut}` : pluginName,
                        shortcut: valid.shortcut,
                        confirm: valid.confirm,
                        tone: valid.tone,
                        order: valid.order ?? valid.priority ?? 0,
                        action: valid.action,
                    });
                }
                continue;
            }
            const resolved = resolveMetaCommand(row, raw);
            if (resolved && !byKey.has(resolved.key)) {
                byKey.set(resolved.key, resolved);
            }
        }
    }

    return [...byKey.values()].sort((a, b) => {
        if (a.order !== b.order) return a.order - b.order;
        const pid = a.pluginId.localeCompare(b.pluginId);
        return pid !== 0 ? pid : a.commandId.localeCompare(b.commandId);
    });
}

export async function runSlotDescriptorAction(
    pluginId: string,
    action: SlotAction,
    opts: {
        readonly sessionRef?: string | null;
        readonly confirm?: string | null;
        readonly title?: string | null;
        readonly tone?: Tone | null;
        readonly fetcher?: typeof authFetch;
    } = {},
): Promise<unknown> {
    if (opts.confirm) {
        const ok = await confirmOk({
            title: opts.title || pluginId,
            message: opts.confirm,
            variant: opts.tone === 'danger' ? 'danger' : 'plain',
        });
        if (!ok) return false;
    }
    if (action.kind === 'href') {
        if (action.external) {
            if (typeof window !== 'undefined' && typeof window.open === 'function') {
                window.open(action.href, '_blank', 'noopener,noreferrer');
            }
        } else if (typeof window !== 'undefined') {
            if (action.href.startsWith('#')) {
                window.location.hash = action.href;
            } else if (typeof window.location?.assign === 'function') {
                window.location.assign(action.href);
            }
        }
        return { href: action.href, external: action.external };
    }
    return executeSlotAction(pluginId, action, { sessionRef: opts.sessionRef, fetcher: opts.fetcher });
}

export function normalizePluginChord(raw: unknown, family: KeyboardFamily): string {
    if (typeof raw !== 'string') return '';
    const trimmed = raw.trim();
    if (!trimmed || trimmed.length > MAX_LABEL) return '';
    const plusKey = trimmed.endsWith('++');
    const body = plusKey ? trimmed.slice(0, -2) : trimmed;
    const parts = body === '' ? [] : body.split('+');
    const keyPart = plusKey ? '+' : (parts.pop() ?? '');
    if (!keyPart) return '';

    const mods: string[] = [];
    for (const part of parts) {
        const lower = part.trim().toLowerCase();
        if (!lower) return '';
        if (lower === 'cmdorctrl' || lower === 'commandorcontrol') {
            mods.push(family === 'mac' ? 'cmd' : 'ctrl');
            continue;
        }
        const mapped = FAMILY_MOD_ALIASES[lower];
        if (!mapped) return '';
        mods.push(mapped);
    }
    const lowerKey = keyPart.trim().toLowerCase();
    const foldedKey = lowerKey === 'space' ? 'space' : lowerKey;
    const joined = [...mods, foldedKey].join('+');
    return normalize(joined);
}

export function isTextEditingChord(mods: readonly string[], key: string): boolean {
    const edits = mods.includes('cmd') || mods.includes('alt');
    return edits && (CARET_KEYS.has(key) || DELETE_KEYS.has(key));
}

export function forbiddenChordSet(family: KeyboardFamily, effectiveBuilt: readonly AppChord[]): Set<string> {
    const forbidden = new Set<string>();
    for (const action of ACTIONS) {
        for (const raw of (action.keys[family] ?? []) as readonly string[]) {
            const canon = normalize(raw);
            if (canon) forbidden.add(canon);
        }
    }
    for (const chord of effectiveBuilt) {
        const canon = normalizePluginChord(chord.accelerator, family);
        if (canon) forbidden.add(canon);
    }
    return forbidden;
}

interface ChordCandidate {
    readonly pluginId: string;
    readonly id: string;
    readonly shortcut: string;
    readonly label: string;
    readonly confirm: string | null;
    readonly tone: Tone | null;
    readonly action: SlotAction;
}

export function resolvePluginChords(
    family: KeyboardFamily,
    effectiveBuilt: readonly AppChord[],
    getSessionRef: () => string | null = () => null,
): AppChord[] {
    const commands = resolvePluginCommands();
    const cmdMap = new Map<string, ResolvedPluginCommand>(commands.map((c) => [c.key, c]));
    const candidates: ChordCandidate[] = [];

    for (const entry of resolveActiveSlots('chords')) {
        if (entry.kind !== 'descriptor' || entry.disabled || !entry.shortcut) continue;
        let action = entry.action;
        if (!action && typeof entry.entry.item.command === 'string') {
            action = cmdMap.get(`${entry.entry.plugin_id}:${entry.entry.item.command}`)?.action ?? null;
        }
        if (!action) continue;
        candidates.push({
            pluginId: entry.entry.plugin_id,
            id: entry.id,
            shortcut: entry.shortcut,
            label: entry.title ?? entry.label,
            confirm: entry.confirm,
            tone: entry.tone,
            action,
        });
    }

    for (const row of pluginsStore.rows) {
        if (!isPluginRowActive(row)) continue;
        const rawChords = Array.isArray(row.chords) ? row.chords : [];
        const contribChords = rowUiContributeList(row, 'chords') ?? [];
        const hasChordConsent = hasSlotConsent(row, 'chords');
        const installKey = typeof row.install_key === 'string' && row.install_key ? row.install_key : row.id;

        for (const raw of rawChords) {
            if (!isPlainObject(raw)) continue;
            if ('disabled' in raw && typeof raw.disabled !== 'boolean') continue;
            if (raw.disabled === true) continue;
            const shortcut = typeof raw.shortcut === 'string' ? raw.shortcut : typeof raw.chord === 'string' ? raw.chord : '';
            if (!shortcut || !isSafeDisplayText(shortcut, MAX_LABEL)) continue;
            const cmdId = typeof raw.command === 'string' ? raw.command : '';
            const rawId = typeof raw.id === 'string' ? raw.id : '';
            const canonShortcut = normalizePluginChord(shortcut, family);
            const isContrib = contribChords.some((c) => {
                const cShortcut = typeof c.shortcut === 'string' ? c.shortcut : typeof c.chord === 'string' ? c.chord : '';
                const cCanon = normalizePluginChord(cShortcut, family);
                const shortcutMatch =
                    canonShortcut && cCanon ? canonShortcut === cCanon : shortcut.trim() === cShortcut.trim();
                if (!shortcutMatch) return false;
                const cCmd = typeof c.command === 'string' ? c.command : '';
                const cId = typeof c.id === 'string' ? c.id : '';
                if (cCmd || cmdId) return cCmd === cmdId;
                if (cId || rawId) return cId === rawId;
                return true;
            });
            if (isContrib && !hasChordConsent) continue;
            if (cmdId) {
                const target = cmdMap.get(`${row.id}:${cmdId}`);
                if (!target) continue;
                candidates.push({
                    pluginId: row.id,
                    id: cmdId,
                    shortcut,
                    label: target.label,
                    confirm: target.confirm,
                    tone: target.tone,
                    action: target.action,
                });
                continue;
            }
            const valid = validateSlotEntry(
                {
                    plugin_id: row.id,
                    install_key: installKey,
                    slot: 'chords',
                    declared_slot: 'chords',
                    item: raw,
                },
                declaredForRow(row),
            );
            if (valid && valid.kind === 'descriptor' && !valid.disabled && valid.action) {
                candidates.push({
                    pluginId: row.id,
                    id: valid.id,
                    shortcut,
                    label: valid.title ?? valid.label,
                    confirm: valid.confirm,
                    tone: valid.tone,
                    action: valid.action,
                });
            }
        }
    }

    for (const cmd of commands) {
        if (!cmd.shortcut) continue;
        candidates.push({
            pluginId: cmd.pluginId,
            id: cmd.commandId,
            shortcut: cmd.shortcut,
            label: cmd.label,
            confirm: cmd.confirm,
            tone: cmd.tone,
            action: cmd.action,
        });
    }

    candidates.sort((a, b) => {
        const pid = a.pluginId.localeCompare(b.pluginId);
        return pid !== 0 ? pid : a.id.localeCompare(b.id);
    });

    const forbidden = forbiddenChordSet(family, effectiveBuilt);
    const seenCanons = new Set<string>();
    const out: AppChord[] = [];

    for (const cand of candidates) {
        const canon = normalizePluginChord(cand.shortcut, family);
        if (!canon) continue;
        if (refusal(family, canon, 'global', ACTIONS) !== null) continue;
        const parsed = parse(canon) as { mods: string[]; key: string };
        if (isTextEditingChord(parsed.mods, parsed.key)) continue;
        if (forbidden.has(canon)) continue;
        if (seenCanons.has(canon)) {
            console.warn('[plugins] duplicate plugin chord ignored:', canon, cand.pluginId, cand.id);
            continue;
        }
        seenCanons.add(canon);

        const matchKey = parsed.key === 'space' ? ' ' : parsed.key;
        out.push({
            id: `cplug.${cand.pluginId}.${cand.id}`,
            key: matchKey,
            meta: parsed.mods.includes('cmd'),
            ctrl: parsed.mods.includes('ctrl'),
            alt: parsed.mods.includes('alt'),
            shift: parsed.mods.includes('shift'),
            anyShift: matchKey.length === 1 && !/[a-z0-9]/.test(matchKey),
            accelerator: cand.shortcut,
            keys: formatChord(canon) as string,
            labelKey: cand.label,
            inFields: false,
            run: () => {
                void runSlotDescriptorAction(cand.pluginId, cand.action, {
                    sessionRef: getSessionRef(),
                    confirm: cand.confirm,
                    title: cand.label,
                    tone: cand.tone,
                }).catch((err: unknown) => console.error('[plugins] chord action failed', cand.pluginId, cand.id, err));
                return true;
            },
        });
    }

    return out;
}

export interface ResolvedProjectPanel {
    readonly pluginId: string;
    readonly entryId: string;
    readonly label: string;
    readonly view: string | null;
    readonly surface: string | null;
    readonly contribution: SlotContribution;
    readonly valid: ValidSlotEntry;
}

export function resolveProjectPanelEntries(): ResolvedProjectPanel[] {
    const out: ResolvedProjectPanel[] = [];
    const seen = new Set<string>();
    for (const valid of resolveActiveSlots('project.panels')) {
        const raw = valid.entry.item;
        const rawLabel =
            valid.kind === 'document'
                ? valid.title || valid.label
                : valid.label || valid.title || valid.id;
        if (!rawLabel || !isSafeDisplayText(rawLabel, MAX_LABEL)) continue;
        const view = typeof raw.view === 'string' && isSafeDisplayText(raw.view, MAX_LABEL) ? raw.view : null;
        const surface = typeof raw.surface === 'string' && isSafeDisplayText(raw.surface, MAX_LABEL) ? raw.surface : null;
        let entryId = valid.id || rawLabel;
        let suffix = 1;
        while (seen.has(`${valid.entry.plugin_id}:${entryId}`)) {
            suffix += 1;
            entryId = `${valid.id || rawLabel}-${suffix}`;
        }
        seen.add(`${valid.entry.plugin_id}:${entryId}`);
        out.push({
            pluginId: valid.entry.plugin_id,
            entryId,
            label: rawLabel,
            view,
            surface,
            contribution: valid.entry,
            valid,
        });
    }
    return out;
}

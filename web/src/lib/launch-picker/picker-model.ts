import type { AccountOption, ComputerLauncher, ProfileRow } from '../launch-profiles-page/api';

export const PHONE_MAX_WIDTH = 640;

export interface PickerRow {
    value: string;
    label: string;
    harness: string;
    icon: string | null;
    account: string;
    followsActive?: boolean;
    model: string;
    modelMode: 'default' | 'fixed' | 'ask';
    badge: string;
    permissions: string;
    isDefault: boolean;
    connectionId: string | null;
    tags: string[];
    detail: string;
    disabled: boolean;
    data: Record<string, string>;
    id?: string;
    hint?: string;
    kind?: string;
    kindTag?: string;
    enrichFrom?: string;
}

export interface RowWords {
    followActive: string;
    modelDefault: string;
    modelAsk: string;
}

export function rowsFromProfiles(profiles: readonly ProfileRow[], accounts: readonly AccountOption[], words: RowWords): PickerRow[] {
    return profiles.map((p) => {
        const pinned = p.account.mode === 'pinned';
        const account = pinned ? (accounts.find((a) => a.id === p.account.account_id)?.name ?? p.account.account_id ?? '') : words.followActive;
        const model = p.model.mode === 'fixed' ? (p.model.value ?? '') : p.model.mode === 'ask' ? words.modelAsk : words.modelDefault;
        return {
            value: p.id, label: p.label || p.id, harness: p.harness, icon: p.icon, account, followsActive: !pinned, model, modelMode: p.model.mode,
            badge: p.summary.permissions_badge, permissions: p.permissions, isDefault: p.default,
            connectionId: p.endpoint.mode === 'connection' ? p.endpoint.connection_id : null,
            tags: [], detail: '', disabled: false, data: {},
        };
    });
}

export function enrichRows(rows: readonly PickerRow[], profiles: readonly ProfileRow[], accounts: readonly AccountOption[], words: RowWords): PickerRow[] {
    const byId = new Map(rowsFromProfiles(profiles, accounts, words).map((r) => [r.value, r]));
    return rows.map((row) => {
        const hit = byId.get(row.enrichFrom ?? row.value);
        if (!hit) return row;
        return { ...row, harness: row.harness || hit.harness, icon: row.icon ?? hit.icon, account: hit.account, followsActive: hit.followsActive, model: hit.model,
            modelMode: hit.modelMode, badge: hit.badge, permissions: hit.permissions, isDefault: hit.isDefault, connectionId: hit.connectionId };
    });
}

export function initialSelection(
    rows: readonly PickerRow[],
    opts: { preselect?: string | null; projectDefault?: string | null; harness?: string | null } = {},
): { value: string; reason: 'preselect' | 'project' | 'default' | 'first' | 'none' } {
    const live = rows.filter((r) => !r.disabled);
    const has = (v?: string | null): v is string => !!v && live.some((r) => r.value === v);
    if (has(opts.preselect)) return { value: opts.preselect, reason: 'preselect' };
    if (has(opts.projectDefault)) return { value: opts.projectDefault, reason: 'project' };
    const scoped = opts.harness ? live.filter((r) => r.harness === opts.harness) : live;
    const pool = scoped.length ? scoped : live;
    const def = pool.find((r) => r.isDefault);
    if (def) return { value: def.value, reason: 'default' };
    if (pool[0]) return { value: pool[0].value, reason: 'first' };
    return { value: '', reason: 'none' };
}

export function isPhoneWidth(width: number): boolean {
    return width > 0 && width <= PHONE_MAX_WIDTH;
}

export function isValidModelId(model: string): boolean {
    return /^(?!-)[A-Za-z0-9._~/-]{1,120}$/.test(model);
}

export function answerFor(row: PickerRow | undefined, model: string): { profileId: string; model: string | null } | null {
    if (!row) return null;
    const asked = row.modelMode === 'ask' ? model.trim() : '';
    return { profileId: row.value, model: asked || null };
}

export const FAMILIES: readonly string[] = ['claude', 'codex', 'hermes', 'openclaw', 'shell'];

export function farRows(launchers: readonly ComputerLauncher[] | null, families: readonly string[] = FAMILIES): PickerRow[] {
    const base = { icon: null, account: '', model: '', modelMode: 'default' as const, badge: '', permissions: 'harness_default', connectionId: null, tags: [], detail: '', disabled: false, data: {} };
    if (launchers) return launchers.map((l, i) => ({ ...base, value: l.id, label: l.name || l.id, harness: l.family, isDefault: i === 0 }));
    return families.map((f, i) => ({ ...base, value: f, label: f, harness: f, isDefault: i === 0 }));
}

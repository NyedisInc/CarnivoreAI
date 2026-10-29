import { authFetch } from '../../opscenter/api/auth.svelte';
import { autoSleep, saveAutoSleep, saveUnreadPolicy } from '../auto-sleep/auto-sleep-store.svelte';
import { settingById, type ConfigField } from './settings-registry';

export interface MaskedSecret {
    configured: boolean;
}

export interface SettingsSummary {
    workspace?: { development_root?: string; default_shell?: string; default_editor?: string; env?: Record<string, string> };
    server_prefs?: { bind_host?: string; effective_bind_host?: string | null; tls_preferred?: boolean; developer_mode?: boolean };
    server?: { host?: string; wildcard_bind?: boolean };
    notifications?: Record<string, unknown>;
    workspace_warnings?: string[] | null;
}

export type SettingsPatch = Partial<Record<ConfigField['group'], Record<string, unknown>>>;

export interface EnvRow {
    name: string;
    value: string;
}

export type RowStatus = { state: 'saving' } | { state: 'saved' } | { state: 'error'; message: string };

export interface SettingsDocApi {
    get(): Promise<SettingsSummary>;
    patch(body: SettingsPatch): Promise<SettingsSummary>;
    saveMinutes(minutes: number): Promise<boolean>;
    minutes(): { value: number; min: number; max: number } | null;
    saveUnreadMinutes?(minutes: number): Promise<boolean>;
    unreadMinutes?(): number | null;
}

export const SAVED_MARK_MS = 2400;

const defaultApi: SettingsDocApi = {
    get: () => authFetch<SettingsSummary>('/config/settings'),
    patch: (body) => authFetch<SettingsSummary>('/config/settings', { method: 'PATCH', body: JSON.stringify(body) }),
    saveMinutes: (minutes) => saveAutoSleep(autoSleep.data?.enabled ?? true, minutes),
    saveUnreadMinutes: (minutes) => saveUnreadPolicy({ unread_idle_minutes: minutes }),
    unreadMinutes: () => autoSleep.data?.unread_idle_minutes ?? null,
    minutes: () => {
        const data = autoSleep.data;
        return data ? { value: data.idle_minutes, min: data.min_idle_minutes, max: data.max_idle_minutes } : null;
    },
};

export function envMap(rows: readonly EnvRow[]): Record<string, string> {
    const out: Record<string, string> = {};
    for (const row of rows) {
        const name = row.name.trim();
        if (name) out[name] = row.value;
    }
    return out;
}

function envKey(map: Record<string, string>): string {
    return JSON.stringify(Object.keys(map).sort().map((k) => [k, String(map[k] ?? '')]));
}

export function envRows(map: Record<string, string> | undefined): EnvRow[] {
    const rows = Object.keys(map ?? {}).sort().map((name) => ({ name, value: String(map?.[name] ?? '') }));
    return rows.length ? rows : [{ name: '', value: '' }];
}

/* address in force */
export function bindState(saved: string, effective: string | null | undefined): 'unmeasured' | 'unset' | 'in-force' | 'pending' {
    if (!effective) return 'unmeasured';
    if (!saved) return 'unset';
    return saved === effective ? 'in-force' : 'pending';
}

export class SettingsDoc {
    summary = $state<SettingsSummary | null>(null);
    loadError = $state<string | null>(null);
    drafts = $state<Record<string, unknown>>({});
    saving = $state(false);
    saveError = $state<string | null>(null);
    warnings = $state<string[]>([]);
    status = $state<Record<string, RowStatus>>({});

    readonly #api: SettingsDocApi;
    readonly #timers = new Map<string, ReturnType<typeof setTimeout>>();

    constructor(api: SettingsDocApi = defaultApi) {
        this.#api = api;
    }

    async load(): Promise<void> {
        try {
            this.summary = await this.#api.get();
            this.loadError = null;
        } catch (error) {
            this.loadError = error instanceof Error ? error.message : String(error);
        }
    }

    seed(id: string): unknown {
        const def = settingById(id);
        const s = this.summary ?? {};
        if (!def) return undefined;
        const control = def.control;
        if (control.kind === 'text') return String((s[control.field.group] as Record<string, unknown> | undefined)?.[control.field.key] ?? '');
        if (control.kind === 'secret') return '';
        if (control.kind === 'env') return envRows(s.workspace?.env);
        if (control.kind === 'bind') return s.server_prefs?.bind_host ?? '';
        if (control.kind === 'auto-sleep-minutes') return this.#api.minutes()?.value ?? null;
        if (control.kind === 'auto-sleep-unread-minutes') return this.#api.unreadMinutes?.() ?? null;
        return undefined;
    }

    value(id: string): unknown {
        return id in this.drafts ? this.drafts[id] : this.seed(id);
    }

    #differs(id: string, value: unknown): boolean {
        const def = settingById(id);
        if (!def) return false;
        if (def.control.kind === 'env') {
            return envKey(envMap(value as EnvRow[])) !== envKey(envMap(this.seed(id) as EnvRow[]));
        }
        if (def.control.kind === 'secret') return value !== '';
        return value !== this.seed(id);
    }

    setDraft(id: string, value: unknown): void {
        const next = { ...this.drafts };
        if (this.#differs(id, value)) next[id] = value;
        else delete next[id];
        this.drafts = next;
        this.saveError = null;
    }

    get dirtyIds(): string[] {
        return Object.keys(this.drafts);
    }

    get invalidIds(): string[] {
        const bad: string[] = [];
        const minutes = this.drafts['auto_sleep_minutes'];
        const range = this.#api.minutes();
        if (minutes !== undefined && range) {
            const n = Number(minutes);
            if (!Number.isInteger(n) || n < range.min || n > range.max) bad.push('auto_sleep_minutes');
        }
        const unread = this.drafts['auto_sleep_unread_minutes'];
        if (unread !== undefined && range) {
            const n = Number(unread);
            if (!Number.isInteger(n) || n < range.min || n > range.max) bad.push('auto_sleep_unread_minutes');
        }
        return bad;
    }

    patch(): SettingsPatch {
        const body: SettingsPatch = {};
        const put = (field: ConfigField, value: unknown): void => {
            (body[field.group] ??= {})[field.key] = value;
        };
        for (const id of this.dirtyIds) {
            const control = settingById(id)?.control;
            const value = this.drafts[id];
            if (!control) continue;
            if (control.kind === 'text' || control.kind === 'secret') put(control.field, value);
            else if (control.kind === 'env') put({ group: 'workspace', key: 'env' }, envMap(value as EnvRow[]));
            else if (control.kind === 'bind') put({ group: 'server_prefs', key: 'bind_host' }, value);
        }
        return body;
    }

    #mark(id: string, status: RowStatus | null): void {
        const timer = this.#timers.get(id);
        if (timer) clearTimeout(timer);
        const next = { ...this.status };
        if (status) next[id] = status;
        else delete next[id];
        this.status = next;
        if (status?.state === 'saved') {
            this.#timers.set(id, setTimeout(() => this.#mark(id, null), SAVED_MARK_MS));
        }
    }

    #settle(ids: readonly string[], sent: Readonly<Record<string, string>>): void {
        const rest = { ...this.drafts };
        for (const id of ids) {
            if (id in rest && JSON.stringify(rest[id]) === sent[id]) delete rest[id];
        }
        this.drafts = rest;
    }

    async save(): Promise<boolean> {
        if (this.saving || !this.dirtyIds.length || this.invalidIds.length) return false;
        this.saving = true;
        this.saveError = null;
        const ids = this.dirtyIds;
        const sent: Record<string, string> = Object.fromEntries(ids.map((id) => [id, JSON.stringify(this.drafts[id])]));
        const body = this.patch();
        const minuteIds: string[] = ids.filter((id) => id === 'auto_sleep_minutes' || id === 'auto_sleep_unread_minutes');
        const patchIds = ids.filter((id) => !minuteIds.includes(id));
        const pending = new Set(ids);
        const done = (group: readonly string[]): void => {
            this.#settle(group, sent);
            for (const id of group) {
                pending.delete(id);
                this.#mark(id, { state: 'saved' });
            }
        };
        for (const id of ids) this.#mark(id, { state: 'saving' });
        try {
            if (Object.keys(body).length) {
                this.summary = await this.#api.patch(body);
                this.warnings = this.summary?.workspace_warnings ?? [];
            }
            done(patchIds);
            const minuteWrites: ReadonlyArray<[string, SettingsDocApi['saveMinutes'] | undefined]> = [
                ['auto_sleep_minutes', this.#api.saveMinutes],
                ['auto_sleep_unread_minutes', this.#api.saveUnreadMinutes],
            ];
            for (const [id, write] of minuteWrites) {
                if (!minuteIds.includes(id) || !write) continue;
                if (!(await write.call(this.#api, Number(JSON.parse(sent[id] ?? 'null'))))) throw new Error('auto-sleep');
                done([id]);
            }
            return true;
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            this.saveError = message;
            for (const id of pending) this.#mark(id, { state: 'error', message });
            return false;
        } finally {
            this.saving = false;
        }
    }

    discard(): void {
        this.drafts = {};
        this.saveError = null;
        for (const id of Object.keys(this.status)) {
            if (this.status[id]?.state === 'error') this.#mark(id, null);
        }
    }

    async applyToggle(id: string, field: ConfigField, value: boolean): Promise<boolean> {
        this.#mark(id, { state: 'saving' });
        try {
            this.summary = await this.#api.patch({ [field.group]: { [field.key]: value } });
            this.#mark(id, { state: 'saved' });
            return true;
        } catch (error) {
            this.#mark(id, { state: 'error', message: error instanceof Error ? error.message : String(error) });
            return false;
        }
    }

    async track(id: string, run: () => Promise<string | null>): Promise<void> {
        this.#mark(id, { state: 'saving' });
        const why = await run();
        this.#mark(id, why ? { state: 'error', message: why } : { state: 'saved' });
    }
}

export const settingsDoc = new SettingsDoc();

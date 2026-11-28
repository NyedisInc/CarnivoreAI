import { auth, authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { LIVENESS } from '../resource-push/store';
import {
    CPLUGS_ROUTE,
    toCplugItem,
    type CplugDevLease,
    type CplugEventsDecl,
    type CplugGitSource,
    type CplugItem,
    type CplugRow,
    type CplugSecretStatus,
    type CplugServicesDecl,
    type CplugSheet,
    type CplugWarning,
    type CplugWatchdog,
} from '../plugins-page/cplugs-adapter';
import type { CplugSlotsResponse, PopoutConfigDecl, SidebarTabDecl, SlotContribution } from './types';
import type { Translate } from '../sessions/types';

export type { CplugSlotsResponse, PopoutConfigDecl, SidebarTabDecl, SlotContribution };

export const CPLUGS_TOPIC = 'cplugs';
export const CPLUG_SLOTS_TOPIC = 'cplug_slots';
export const CPLUG_SLOTS_ROUTE = '/cplugs/slots';
export const CPLUG_INSPECTOR_TOPIC = 'cplug_inspector';
export const POLL_MS = 60_000;

export const SLOT_ALIASES: Readonly<Record<string, string>> = {
    session_row_actions: 'session.row_actions',
    session_badges: 'session.badges',
    terminal_toolbar: 'terminal.toolbar',
    project_panels: 'project.panels',
};

export function canonicalSlotName(slotName: string): string {
    return SLOT_ALIASES[slotName] ?? slotName;
}

export interface RefreshOptions {
    readonly force?: boolean;
    readonly allowSignedOut?: boolean;
    readonly includeAgentPlugins?: boolean;
    readonly includeSlots?: boolean;
}

export interface AcquireOptions {
    readonly allowSignedOut?: boolean;
    readonly includeAgentPlugins?: boolean;
    readonly includeSlots?: boolean;
}

export interface DeclarativeWidgetDecl {
    readonly id?: string;
    readonly title?: string;
    readonly sizes?: readonly string[];
    readonly mode?: string;
    readonly fits?: {
        readonly sizes?: readonly string[];
        readonly min?: { readonly w?: number; readonly h?: number };
        readonly anySize?: boolean;
    };
    readonly instancing?: 'singleton' | 'per-target';
    readonly settings?: unknown;
    readonly glance?: unknown;
    readonly ui_file?: string;
    readonly document?: unknown;
    readonly popout?: boolean | PopoutConfigDecl;
}

export interface WatchdogSummary extends CplugWatchdog {
    readonly last_call?: string | null;
    readonly last_event?: string | null;
}

export interface StoreCplugRow extends CplugRow {
    readonly declarative_widget?: DeclarativeWidgetDecl | null;
    readonly sidebar_tab?: SidebarTabDecl | null;
    readonly watchdog?: WatchdogSummary | null;
    readonly install_id?: string;
    readonly macros?: readonly string[] | null;
}

export interface GithubPreviewRequest {
    readonly source: string;
    readonly ref?: string | null;
    readonly subdir?: string;
    readonly scope?: 'global' | 'project';
    readonly project_path?: string | null;
}

export interface GithubPreviewPermission {
    readonly name: string;
    readonly risk?: string;
    readonly reason?: string;
    readonly granted?: boolean;
    readonly needs_tick?: boolean;
}

export interface GithubPreviewSecret {
    readonly name: string;
    readonly label?: string;
    readonly hosts?: readonly string[];
}

export interface GithubPreviewResponse {
    readonly id?: string;
    readonly item_id?: string;
    readonly name?: string | null;
    readonly description?: string | null;
    readonly version?: string;
    readonly kind?: string;
    readonly trust_tier?: string;
    readonly trust_badge?: string;
    readonly unverified?: boolean;
    readonly code_sha256?: string;
    readonly digest?: string;
    readonly body_sha?: string;
    readonly permissions?: readonly GithubPreviewPermission[];
    readonly risks?: Readonly<Record<string, string>>;
    readonly reasons?: readonly string[];
    readonly warnings?: readonly (CplugWarning | string)[];
    readonly consent_sheet?: CplugSheet | Readonly<Record<string, unknown>>;
    readonly secrets?: readonly GithubPreviewSecret[];
    readonly ui_slots?: readonly string[];
    readonly ui_contribute?: Readonly<Record<string, readonly Readonly<Record<string, unknown>>[]>>;
    readonly declared_ui_slots?: readonly string[];
    readonly services?: CplugServicesDecl;
    readonly events?: CplugEventsDecl;
    readonly supported_scopes?: readonly ('global' | 'project')[];
    readonly source?: CplugGitSource;
    readonly runtime_active?: boolean;
    readonly scope?: 'global' | 'project';
    readonly project_path?: string | null;
    readonly [key: string]: unknown;
}

export interface GithubInstallRequest {
    readonly source: string;
    readonly ref?: string | null;
    readonly subdir?: string;
    readonly name?: string | null;
    readonly scope?: 'global' | 'project';
    readonly project_path?: string | null;
    readonly enable?: boolean;
    readonly activate_runtime?: boolean;
    readonly secrets?: Readonly<Record<string, string>>;
    readonly ui_slots?: readonly string[] | null;
    readonly consent?: Readonly<Record<string, unknown>> | null;
}

export interface GithubInstallResponse {
    readonly id: string;
    readonly item_id?: string;
    readonly install_key?: string;
    readonly kind: string;
    readonly trust_tier: string;
    readonly trust_badge: string;
    readonly unverified: boolean;
    readonly code_sha256: string;
    readonly scope: 'global' | 'project';
    readonly supported_scopes?: readonly ('global' | 'project')[];
    readonly project_path?: string | null;
    readonly enabled: boolean;
    readonly runtime_active: boolean;
    readonly secrets_status?: Readonly<Record<string, CplugSecretStatus>>;
    readonly git?: CplugGitSource;
    readonly targets?: readonly string[];
    readonly [key: string]: unknown;
}

export interface PluginUpdateRequest {
    readonly revision?: number;
    readonly enabled?: boolean;
    readonly grants?: { readonly app: readonly string[]; readonly ui_slots?: readonly string[] | null };
    readonly settings?: Readonly<Record<string, unknown>>;
    readonly consent?: Readonly<Record<string, unknown>>;
    readonly confirm_dependents?: boolean;
    readonly activate_runtime?: boolean;
    readonly secrets?: Readonly<Record<string, string>>;
}

export interface InspectorRpcTraceEntry {
    readonly seq?: number;
    readonly ts: number;
    readonly source: 'rpc' | 'cli_sock' | string;
    readonly method: string;
    readonly target?: string | null;
    readonly latency_ms?: number;
    readonly ok: boolean;
    readonly error_code?: string | null;
    readonly error_message?: string | null;
}

export interface InspectorCapabilityCheck {
    readonly seq?: number;
    readonly ts: number;
    readonly permission: string;
    readonly allowed: boolean;
    readonly reason?: string | null;
    readonly caller?: string | null;
}

export interface InspectorSurfacesSummary {
    readonly widget: boolean;
    readonly panel: boolean;
    readonly bar: boolean;
    readonly settings: boolean;
    readonly views: readonly string[];
    readonly absent_surfaces?: readonly string[];
    readonly tools: readonly string[];
    readonly routes: readonly string[];
    readonly timers?: readonly string[];
}

export interface InspectorLogEntry {
    readonly source: string;
    readonly line?: string;
    readonly seq?: number;
    readonly ts?: number;
    readonly payload?: Readonly<Record<string, unknown>>;
}

export interface PluginInspectorSnapshot {
    readonly cplug_id: string;
    readonly plugin_id?: string;
    readonly install_key?: string;
    readonly kind?: string;
    readonly trust_tier?: string;
    readonly trust_badge?: string;
    readonly unverified?: boolean;
    readonly state: string;
    readonly paused: boolean;
    readonly watchdog: WatchdogSummary;
    readonly surfaces?: InspectorSurfacesSummary;
    readonly dev_lease?: CplugDevLease | null;
    readonly secrets_status?: Readonly<Record<string, CplugSecretStatus>>;
    readonly rpc_trace: readonly InspectorRpcTraceEntry[];
    readonly capability_checks: readonly InspectorCapabilityCheck[];
    readonly logs_tail: readonly InspectorLogEntry[];
}

export function errorMessageOf(err: unknown): string {
    if (err && typeof err === 'object') {
        const record = err as { payload?: unknown; detail?: unknown; message?: unknown };
        const body = record.payload && typeof record.payload === 'object'
            ? (record.payload as { detail?: unknown; message?: unknown })
            : record;
        const detail = body.detail;
        if (typeof detail === 'string' && detail) return detail;
        if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
            const inner = detail as { detail?: unknown; message?: unknown };
            if (typeof inner.detail === 'string' && inner.detail) return inner.detail;
            if (typeof inner.message === 'string' && inner.message) return inner.message;
        }
        if (Array.isArray(detail) && detail.length > 0) {
            const msgs = detail
                .map((item) => (item && typeof item === 'object' ? (item as { msg?: unknown }).msg : null))
                .filter((msg): msg is string => typeof msg === 'string' && msg.length > 0);
            if (msgs.length > 0) return msgs.join('; ');
        }
    }
    if (err instanceof Error && err.message) return err.message;
    if (err && typeof err === 'object' && typeof (err as { message?: unknown }).message === 'string') {
        const msg = (err as { message: string }).message;
        if (msg) return msg;
    }
    return String(err);
}

export type RowsListener = (rows: readonly StoreCplugRow[]) => void;
export type SlotsListener = (
    slots: Readonly<Record<string, readonly SlotContribution[]>>,
    owners: Readonly<Record<string, string>>,
) => void;

export class PluginsStore {
    rows = $state<readonly StoreCplugRow[]>([]);
    read = $state(false);
    loading = $state(false);
    error = $state<string | null>(null);
    enabled = $state<Record<string, boolean>>({});
    settings = $state<Record<string, Record<string, unknown>>>({});
    inspectors = $state<Record<string, PluginInspectorSnapshot>>({});
    slots = $state<Record<string, readonly SlotContribution[]>>({});
    slotOwners = $state<Record<string, string>>({});
    slotsRead = $state(false);

    #refs = 0;
    #allowSignedOutRefs = 0;
    #includeAgentPluginsRefs = 0;
    #inFlight: Promise<boolean> | null = null;
    #inFlightAgentPlugins = false;
    #rowsIncludeAgentPlugins = false;
    #stopPush: (() => void) | null = null;
    #slotRefs = 0;
    #slotAllowSignedOutRefs = 0;
    #slotsInFlight: Promise<boolean> | null = null;
    #stopSlotsPush: (() => void) | null = null;
    readonly #inspectorSubs = new Map<string, { refs: number; installKeys: Set<string>; stop: (() => void) | null }>();
    readonly #rowListeners = new Set<RowsListener>();
    readonly #slotListeners = new Set<SlotsListener>();
    readonly #syncListeners = new Set<RowsListener>();
    readonly #resetListeners = new Set<() => void>();

    rowOf(id: string): StoreCplugRow | undefined {
        return this.rows.find((row) => row.id === id);
    }

    inspectorOf(id: string): PluginInspectorSnapshot | null {
        return this.inspectors[id] ?? null;
    }

    slotsFor(slotName: string): readonly SlotContribution[] {
        const canonical = canonicalSlotName(slotName);
        return this.slots[canonical] ?? [];
    }

    slotOwnerOf(slotName: string): string | undefined {
        const canonical = canonicalSlotName(slotName);
        return this.slotOwners[canonical];
    }

    onSlots(fn: SlotsListener): () => void {
        this.#slotListeners.add(fn);
        return () => {
            this.#slotListeners.delete(fn);
        };
    }

    #emitSlots(
        slots: Readonly<Record<string, readonly SlotContribution[]>>,
        owners: Readonly<Record<string, string>>,
    ): void {
        for (const fn of [...this.#slotListeners]) {
            try {
                fn(slots, owners);
            } catch {
            }
        }
    }

    items(t: Translate): CplugItem[] {
        return this.rows.map((row) => toCplugItem(row, t));
    }

    onRows(fn: RowsListener): () => void {
        this.#rowListeners.add(fn);
        return () => {
            this.#rowListeners.delete(fn);
        };
    }

    onSync(fn: RowsListener): () => void {
        this.#syncListeners.add(fn);
        return () => {
            this.#syncListeners.delete(fn);
        };
    }

    onReset(fn: () => void): () => void {
        this.#resetListeners.add(fn);
        return () => {
            this.#resetListeners.delete(fn);
        };
    }

    #emitRows(rows: readonly CplugRow[]): void {
        for (const fn of [...this.#syncListeners]) {
            try {
                fn(rows);
            } catch {
            }
        }
        for (const fn of [...this.#rowListeners]) {
            try {
                fn(rows);
            } catch {
            }
        }
    }

    async refresh(opts: RefreshOptions = {}): Promise<boolean> {
        if (auth.state === 'signed-out' && !opts.allowSignedOut) return false;
        const shouldRefreshSlots = opts.includeSlots === true || this.#slotRefs > 0 || this.slotsRead;
        const includeAgentPlugins = opts.includeAgentPlugins === true || this.#includeAgentPluginsRefs > 0;
        const pending = this.#inFlight;
        if (pending) {
            if (!opts.force && (!includeAgentPlugins || this.#inFlightAgentPlugins)) {
                if (opts.includeSlots) {
                    const [rowsOk] = await Promise.all([
                        pending,
                        this.refreshSlots({ force: opts.force, allowSignedOut: opts.allowSignedOut }),
                    ]);
                    return rowsOk;
                }
                return pending;
            }
            await pending.catch(() => false);
            if (this.#inFlight && (!includeAgentPlugins || this.#inFlightAgentPlugins)) {
                if (opts.includeSlots) {
                    const [rowsOk] = await Promise.all([
                        this.#inFlight,
                        this.refreshSlots({ force: opts.force, allowSignedOut: opts.allowSignedOut }),
                    ]);
                    return rowsOk;
                }
                return this.#inFlight;
            }
        }
        const path = includeAgentPlugins ? `${CPLUGS_ROUTE}?include_agent_plugins=true` : CPLUGS_ROUTE;
        let run!: Promise<boolean>;
        run = (async (): Promise<boolean> => {
            this.loading = true;
            this.error = null;
            try {
                const body = await authFetch<{ cplugs?: StoreCplugRow[] }>(path);
                const nextRows = Array.isArray(body?.cplugs) ? body.cplugs : [];
                const nextEnabled: Record<string, boolean> = {};
                const nextSettings: Record<string, Record<string, unknown>> = {};
                for (const row of nextRows) {
                    if (row.state === 'removed') continue;
                    nextEnabled[row.id] = row.enabled === true;
                    nextSettings[row.id] = row.settings && typeof row.settings === 'object' ? { ...row.settings } : {};
                }
                this.rows = nextRows;
                this.#rowsIncludeAgentPlugins = includeAgentPlugins;
                this.enabled = nextEnabled;
                this.settings = nextSettings;
                this.read = true;
                this.#emitRows(nextRows);
                return true;
            } catch (err) {
                this.error = errorMessageOf(err);
                return false;
            } finally {
                this.loading = false;
                if (this.#inFlight === run) {
                    this.#inFlight = null;
                    this.#inFlightAgentPlugins = false;
                }
            }
        })();
        this.#inFlightAgentPlugins = includeAgentPlugins;
        this.#inFlight = run;
        if (!shouldRefreshSlots) return run;
        const [rowsOk] = await Promise.all([
            run,
            this.refreshSlots({ force: opts.force, allowSignedOut: opts.allowSignedOut }),
        ]);
        return rowsOk;
    }

    async refreshSlots(opts: { readonly force?: boolean; readonly allowSignedOut?: boolean } = {}): Promise<boolean> {
        if (auth.state === 'signed-out' && !opts.allowSignedOut) return false;
        const pending = this.#slotsInFlight;
        if (pending) {
            if (!opts.force) return pending;
            await pending.catch(() => false);
            if (this.#slotsInFlight) return this.#slotsInFlight;
        }
        let run!: Promise<boolean>;
        run = (async (): Promise<boolean> => {
            try {
                const body = await authFetch<Partial<CplugSlotsResponse>>(CPLUG_SLOTS_ROUTE);
                const nextSlots: Record<string, readonly SlotContribution[]> = {};
                if (body?.slots && typeof body.slots === 'object' && !Array.isArray(body.slots)) {
                    for (const [key, list] of Object.entries(body.slots)) {
                        const canonical = canonicalSlotName(key);
                        if (Array.isArray(list)) {
                            nextSlots[canonical] = [...(nextSlots[canonical] ?? []), ...list];
                        }
                    }
                }
                const nextOwners: Record<string, string> = {};
                if (body?.owners && typeof body.owners === 'object' && !Array.isArray(body.owners)) {
                    for (const [key, owner] of Object.entries(body.owners)) {
                        if (typeof owner === 'string') nextOwners[canonicalSlotName(key)] = owner;
                    }
                }
                this.slots = nextSlots;
                this.slotOwners = nextOwners;
                this.slotsRead = true;
                this.#emitSlots(nextSlots, nextOwners);
                return true;
            } catch {
                return false;
            } finally {
                if (this.#slotsInFlight === run) {
                    this.#slotsInFlight = null;
                }
            }
        })();
        this.#slotsInFlight = run;
        return run;
    }

    acquireSlots(opts: { readonly allowSignedOut?: boolean } = {}): () => void {
        if (auth.state === 'signed-out' && !opts.allowSignedOut) return () => {};
        this.#slotRefs += 1;
        const countedSignedOut = opts.allowSignedOut === true;
        if (countedSignedOut) this.#slotAllowSignedOutRefs += 1;
        if (this.#slotRefs === 1) {
            const push = resourcePush();
            const stop = push.pushOrPoll(
                () => {
                    void this.refreshSlots({
                        force: true,
                        allowSignedOut: this.#slotAllowSignedOutRefs > 0,
                    });
                },
                POLL_MS,
                [CPLUG_SLOTS_TOPIC],
            );
            this.#stopSlotsPush = typeof stop === 'function' ? stop : null;
        }
        void this.refreshSlots({ allowSignedOut: countedSignedOut });
        let released = false;
        return () => {
            if (released) return;
            released = true;
            this.#slotRefs = Math.max(0, this.#slotRefs - 1);
            if (countedSignedOut) this.#slotAllowSignedOutRefs = Math.max(0, this.#slotAllowSignedOutRefs - 1);
            if (this.#slotRefs === 0) {
                this.#stopSlotsPush?.();
                this.#stopSlotsPush = null;
            }
        };
    }

    acquire(opts: AcquireOptions = {}): () => void {
        if (auth.state === 'signed-out' && !opts.allowSignedOut) return () => {};
        this.#refs += 1;
        const countedSignedOut = opts.allowSignedOut === true;
        const countedAgentPlugins = opts.includeAgentPlugins === true;
        if (countedSignedOut) this.#allowSignedOutRefs += 1;
        if (countedAgentPlugins) this.#includeAgentPluginsRefs += 1;
        if (this.#refs === 1) {
            const push = resourcePush();
            const stop = push.pushOrPoll(
                () => {
                    void this.refresh({
                        force: true,
                        allowSignedOut: this.#allowSignedOutRefs > 0,
                        includeAgentPlugins: this.#includeAgentPluginsRefs > 0,
                    });
                },
                POLL_MS,
                [CPLUGS_TOPIC],
            );
            this.#stopPush = typeof stop === 'function' ? stop : null;
        }
        const stopSlots = opts.includeSlots ? this.acquireSlots({ allowSignedOut: countedSignedOut }) : null;
        void this.refresh({
            force: countedAgentPlugins && !this.#rowsIncludeAgentPlugins && !this.#inFlightAgentPlugins && this.read,
            allowSignedOut: countedSignedOut,
            includeAgentPlugins: this.#includeAgentPluginsRefs > 0,
        });
        let released = false;
        return () => {
            if (released) return;
            released = true;
            stopSlots?.();
            this.#refs = Math.max(0, this.#refs - 1);
            if (countedSignedOut) this.#allowSignedOutRefs = Math.max(0, this.#allowSignedOutRefs - 1);
            if (countedAgentPlugins) this.#includeAgentPluginsRefs = Math.max(0, this.#includeAgentPluginsRefs - 1);
            if (this.#refs === 0) {
                this.#stopPush?.();
                this.#stopPush = null;
            }
        };
    }

    async #runAction<T>(fn: () => Promise<T>): Promise<T> {
        this.error = null;
        try {
            return await fn();
        } catch (err) {
            const message = errorMessageOf(err);
            this.error = message;
            if (err instanceof Error) throw err;
            throw new Error(message);
        }
    }

    previewGithub(body: GithubPreviewRequest): Promise<GithubPreviewResponse> {
        return this.#runAction(() =>
            authFetch<GithubPreviewResponse>('/cplug-owner/github/preview', {
                method: 'POST',
                body: JSON.stringify(body),
            }),
        );
    }

    installGithub(body: GithubInstallRequest): Promise<GithubInstallResponse> {
        return this.#runAction(async () => {
            const installed = await authFetch<GithubInstallResponse>('/cplug-owner/github/install', {
                method: 'POST',
                body: JSON.stringify(body),
            });
            await this.refresh({ force: true, allowSignedOut: true });
            return installed;
        });
    }

    fetchInspector(id: string): Promise<PluginInspectorSnapshot> {
        return this.#runAction(async () => {
            const snapshot = await authFetch<PluginInspectorSnapshot>(`${CPLUGS_ROUTE}/${encodeURIComponent(id)}/inspector`);
            this.inspectors = { ...this.inspectors, [id]: snapshot };
            return snapshot;
        });
    }

    acquireInspector(id: string, installKey?: string | null): () => void {
        if (auth.state === 'signed-out') return () => {};
        const key = typeof installKey === 'string' ? installKey.trim() : '';
        let entry = this.#inspectorSubs.get(id);
        if (!entry) {
            entry = { refs: 0, installKeys: new Set(), stop: null };
            this.#inspectorSubs.set(id, entry);
        }
        entry.refs += 1;
        if (key) entry.installKeys.add(key);
        if (entry.refs === 1) {
            const push = resourcePush();
            const idTopic = `${CPLUG_INSPECTOR_TOPIC}:${id}`;
            const currentEntry = entry;
            const stop = push.onChange((topics) => {
                const matchedTopic =
                    topics.includes(idTopic) ||
                    [...currentEntry.installKeys].some((k) => topics.includes(`${CPLUG_INSPECTOR_TOPIC}:${k}`)) ||
                    (topics.includes(LIVENESS) && push.isLive(idTopic));
                if (matchedTopic) void this.fetchInspector(id).catch(() => undefined);
            });
            currentEntry.stop = typeof stop === 'function' ? stop : null;
            void this.fetchInspector(id).catch(() => undefined);
        }
        let released = false;
        return () => {
            if (released) return;
            released = true;
            const current = this.#inspectorSubs.get(id);
            if (!current) return;
            current.refs = Math.max(0, current.refs - 1);
            if (current.refs === 0) {
                current.stop?.();
                current.stop = null;
                this.#inspectorSubs.delete(id);
            }
        };
    }

    async #refreshInspectorIfTracked(id: string): Promise<void> {
        if (this.inspectors[id] === undefined && !this.#inspectorSubs.has(id)) return;
        const prevError = this.error;
        try {
            await this.fetchInspector(id);
        } catch {
            this.error = prevError;
        }
    }

    pausePlugin(id: string): Promise<Record<string, unknown>> {
        return this.#runAction(async () => {
            const result = await authFetch<Record<string, unknown>>(`${CPLUGS_ROUTE}/${encodeURIComponent(id)}/pause`, {
                method: 'POST',
            });
            await this.refresh({ force: true, allowSignedOut: true });
            await this.#refreshInspectorIfTracked(id);
            return result;
        });
    }

    resumePlugin(id: string): Promise<Record<string, unknown>> {
        return this.#runAction(async () => {
            const result = await authFetch<Record<string, unknown>>(`${CPLUGS_ROUTE}/${encodeURIComponent(id)}/resume`, {
                method: 'POST',
            });
            await this.refresh({ force: true, allowSignedOut: true });
            await this.#refreshInspectorIfTracked(id);
            return result;
        });
    }

    restartPlugin(id: string): Promise<Record<string, unknown>> {
        return this.#runAction(async () => {
            const result = await authFetch<Record<string, unknown>>(`${CPLUGS_ROUTE}/${encodeURIComponent(id)}/restart`, {
                method: 'POST',
            });
            await this.refresh({ force: true, allowSignedOut: true });
            await this.#refreshInspectorIfTracked(id);
            return result;
        });
    }

    updatePlugin(id: string, body: PluginUpdateRequest): Promise<CplugRow> {
        return this.#runAction(async () => {
            const path = `${CPLUGS_ROUTE}/${encodeURIComponent(id)}`;
            let revision = body.revision;
            if (revision === undefined) {
                const current = await authFetch<CplugRow>(path);
                revision = current.revision ?? 0;
            }
            const row = await authFetch<CplugRow>(path, {
                method: 'PUT',
                body: JSON.stringify({ ...body, revision }),
            });
            await this.refresh({ force: true, allowSignedOut: true });
            return row;
        });
    }

    resetForTest(): void {
        this.#stopPush?.();
        this.#stopPush = null;
        this.#stopSlotsPush?.();
        this.#stopSlotsPush = null;
        for (const sub of this.#inspectorSubs.values()) {
            sub.stop?.();
            sub.stop = null;
        }
        this.#inspectorSubs.clear();
        this.#refs = 0;
        this.#allowSignedOutRefs = 0;
        this.#includeAgentPluginsRefs = 0;
        this.#inFlight = null;
        this.#inFlightAgentPlugins = false;
        this.#rowsIncludeAgentPlugins = false;
        this.#slotRefs = 0;
        this.#slotAllowSignedOutRefs = 0;
        this.#slotsInFlight = null;
        this.#rowListeners.clear();
        this.#slotListeners.clear();
        this.rows = [];
        this.read = false;
        this.loading = false;
        this.error = null;
        this.enabled = {};
        this.settings = {};
        this.inspectors = {};
        this.slots = {};
        this.slotOwners = {};
        this.slotsRead = false;
        for (const fn of [...this.#resetListeners]) {
            try {
                fn();
            } catch {
            }
        }
    }
}

export const pluginsStore = new PluginsStore();

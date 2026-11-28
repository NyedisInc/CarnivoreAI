/* the detail pane the plugins page */
import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { icons } from '../../opscenter/ui/icons';
import { revocationOfItem } from '../catalog/revocation';
import { refreshEnablement } from '../../plugins/host/enablement.svelte';
import { MANAGER_KEYS } from '../manager-frame/manager-model';
import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { SettingValue } from '../item-settings/api';
import { pluginsStore, type DeclarativeWidgetDecl } from '../plugins/store.svelte';
import type {
    CplugChannelDecl,
    CplugChordDecl,
    CplugCommandDecl,
    CplugEventsDecl,
    CplugPermissionRisk,
    CplugServiceProvidesDecl,
    CplugServicesDecl,
    CplugUiSlotRow,
    PopoutConfigDecl,
    SidebarTabDecl,
} from '../plugins/types';

export type {
    CplugChannelDecl,
    CplugChordDecl,
    CplugCommandDecl,
    CplugEventsDecl,
    CplugServiceProvidesDecl,
    CplugServicesDecl,
    CplugUiSlotRow,
    PopoutConfigDecl,
    SidebarTabDecl,
};

export const CPLUGS_ROUTE = '/cplugs';
export const CPLUGS_WITH_AGENT_PLUGINS_ROUTE = `${CPLUGS_ROUTE}?include_agent_plugins=true`;
export const CPLUG_ITEM_PREFIX = 'cplug:';
const CPLUG_ROW_KIND = 'cplug' as const;

export function isCplugRow(item: ManagerItem | { readonly kind: string }): item is CplugItem {
    return (item as { readonly kind?: string | null }).kind === CPLUG_ROW_KIND;
}

export interface CplugViewRow {
    readonly name: string;
    readonly surfaces: readonly string[];
    readonly fits?: { readonly sizes?: readonly string[]; readonly min?: { readonly w?: number; readonly h?: number }; readonly anySize?: boolean } | null;
    readonly popout?: boolean | PopoutConfigDecl | null;
}

export interface CplugSurfaces {
    readonly routes?: boolean;
    readonly mcp_tools?: readonly string[];
    readonly topics?: readonly string[];
    readonly tabs?: readonly string[];
    readonly widgets?: readonly string[];
    readonly plugins?: readonly string[];
    readonly menu_links?: readonly string[];
    readonly feed?: boolean;
    readonly storage?: boolean;
}

const TAGGED_SURFACES = ['tabs', 'widgets', 'plugins', 'menu_links', 'mcp_tools', 'feed'] as const;

export interface CplugSecretStatus {
    readonly secret_present?: boolean;
    readonly present?: boolean;
    readonly needs_reentry?: boolean;
}

export interface CplugWatchdog {
    readonly pid?: number | null;
    readonly memory_limit_bytes?: number;
    readonly rss_bytes?: number;
    readonly cpu_seconds?: number;
    readonly cpu_percent?: number;
    readonly disk_bytes?: number;
    readonly disk_quota_bytes?: number;
    readonly disk_files?: number;
    readonly disk_quota_files?: number;
    readonly restart_count?: number;
    readonly strikes?: number;
    readonly crash_loop_paused?: boolean;
    readonly uptime_seconds?: number | null;
    readonly last_call?: string | null;
    readonly last_event?: string | null;
}

export interface CplugDevLease {
    readonly active: boolean;
    readonly source_realpath?: string | null;
    readonly baseline_sha?: string | null;
    readonly ttl_remaining_seconds?: number | null;
}

export interface CplugGitSource {
    readonly url: string;
    readonly ref?: string | null;
    readonly subdir?: string | null;
    readonly commit?: string | null;
    readonly synced_at?: string | null;
    readonly owner?: string | null;
    readonly repo?: string | null;
}

export interface CplugRow {
    readonly id: string;
    readonly name_key?: string;
    readonly description_key?: string;
    readonly version?: string;
    readonly tier?: string;
    readonly kind?: string;
    readonly trust_tier?: string;
    readonly trust_badge?: string | null;
    readonly scope?: string;
    readonly project_path?: string | null;
    readonly runtime_paused?: boolean;
    readonly runtime_active?: boolean;
    readonly secrets_status?: Readonly<Record<string, CplugSecretStatus>>;
    readonly watchdog?: CplugWatchdog | null;
    readonly dev_lease?: CplugDevLease | null;
    readonly git_source?: CplugGitSource | null;
    readonly icon?: string;
    readonly icon_url?: string | null;
    readonly author?: string;
    readonly surfaces?: CplugSurfaces;
    readonly enabled: boolean | null;
    readonly state: string;
    readonly blocked_by?: readonly string[];
    readonly permissions?: { readonly app?: readonly string[] };
    readonly grants?: { readonly app?: readonly string[]; readonly ui_slots?: readonly string[] };
    readonly granted_ui_slots?: readonly string[];
    readonly services?: CplugServicesDecl;
    readonly events?: CplugEventsDecl;
    readonly ui_slots?: readonly string[];
    readonly ui_contribute?: Readonly<Record<string, readonly Readonly<Record<string, unknown>>[]>>;
    readonly commands?: readonly CplugCommandDecl[];
    readonly chords?: readonly CplugChordDecl[];
    readonly session_row_actions?: readonly Readonly<Record<string, unknown>>[];
    readonly session_badges?: readonly unknown[];
    readonly terminal_toolbar?: readonly Readonly<Record<string, unknown>>[];
    readonly project_panels?: readonly Readonly<Record<string, unknown>>[];
    readonly channels?: readonly CplugChannelDecl[];
    readonly harnesses?: readonly string[];
    readonly popout?: boolean | Readonly<Record<string, unknown>> | readonly Readonly<Record<string, unknown>>[] | null;
    readonly revision?: number;
    readonly risks?: Readonly<Record<string, string>>;
    readonly reasons?: Readonly<Record<string, string>>;
    readonly warnings?: readonly CplugWarning[];
    readonly settings_warnings?: readonly SettingsWarning[];
    readonly consent_required?: boolean;
    readonly settings?: Readonly<Record<string, SettingValue>>;
    readonly settings_schema?: WidgetSettingsSchema;
    readonly dependencies?: CplugDependencies;
    readonly needs?: readonly string[];
    readonly detail?: string | null;
    readonly storage_bytes?: number;
    readonly runtime?: 'sidecar' | 'compiled' | 'agent-plugin';
    readonly item_id?: string | null;
    readonly install_id?: string;
    readonly declarative_widget?: DeclarativeWidgetDecl | null;
    readonly sidebar_tab?: SidebarTabDecl | null;
    readonly name?: string | null;
    readonly description?: string | null;
    readonly publisher?: string | null;
    readonly tools?: readonly string[] | null;
    readonly routes?: readonly string[] | null;
    readonly declared_tools?: readonly string[] | null;
    readonly install_key?: string | null;
    readonly unrendered_surfaces?: readonly string[] | null;
    readonly views?: readonly CplugViewRow[] | null;
    readonly page?: { readonly menu: string; readonly main: string; readonly popout?: boolean | PopoutConfigDecl } | null;
    readonly page_problem?: string | null;
    readonly topics?: readonly string[] | null;
    readonly preview?: string | null;
    readonly screenshots?: readonly {
        readonly url?: string | null;
        readonly sha?: string | null;
        readonly w?: number | null;
        readonly h?: number | null;
        readonly source?: 'author' | 'captured' | null;
        readonly surface?: string | null;
        readonly caption?: string | null;
    }[];
    readonly unverified?: boolean;
    readonly changed_files?: readonly string[];
    readonly revoked?: boolean;
    readonly revocation_state?: string | null;
    readonly revocation_reason?: string | null;
    readonly revoked_since?: string | null;
    readonly review_verdict?: string | null;
    readonly flagged?: boolean;
}

export interface CplugDependencies {
    readonly plugins?: readonly { readonly id: string; readonly status: 'on' | 'off' | 'missing' }[];
    readonly core?: readonly { readonly id: string; readonly available: boolean }[];
    readonly min_app_version?: { readonly need: string; readonly have: string; readonly met: boolean };
    readonly needed_by?: readonly { readonly id: string; readonly enabled: boolean }[];
    readonly enabled_dependents?: readonly string[];
}

export interface NeedRow {
    readonly kind: 'plugin' | 'core' | 'version';
    readonly id: string;
    readonly label: string;
    readonly status: 'ok' | 'off' | 'missing';
}

export interface DependencyView {
    readonly needs: readonly NeedRow[];
    readonly neededBy: readonly { readonly id: string; readonly label: string; readonly enabled: boolean }[];
    readonly enabledDependents: readonly string[];
}

export type PermissionRisk = CplugPermissionRisk;

export interface CplugWarning {
    readonly code: string;
    readonly reads?: string;
    readonly host?: string;
}

export interface SettingsWarning {
    readonly code: string;
    readonly message: string;
    readonly field?: string;
    readonly detail?: string;
}

export interface PermissionRow {
    readonly name: string;
    readonly label: string;
    readonly risk: PermissionRisk;
    readonly reason: string;
    readonly granted: boolean;
}

export interface CplugSheet {
    readonly digest: string;
    readonly body_sha: string;
    readonly grants_sha: string;
    readonly permissions: readonly {
        readonly name: string;
        readonly risk: PermissionRisk;
        readonly reason?: string;
        readonly granted: boolean;
        readonly needs_tick?: boolean;
    }[];
    readonly ui_slots?: readonly CplugUiSlotRow[];
    readonly ui_slots_sha?: string;
    readonly kind?: string;
    readonly trust_tier?: string;
    readonly trust_badge?: string | null;
    readonly unverified?: boolean;
    readonly changed_files?: readonly string[];
}

export interface ActivityRow {
    readonly ts: number;
    readonly method: string;
    readonly permission: string;
    readonly target: string;
    readonly status: string;
    readonly bytes: number;
    readonly count: number;
}

export interface CplugItem extends ManagerItem {
    readonly kind: 'cplug';
    readonly cplugId: string;
    readonly version: string;
    readonly iconUrl?: string;
    readonly asks: readonly string[];
    readonly state: string;
    readonly blockedBy: readonly string[];
    readonly permissions: readonly PermissionRow[];
    readonly warnings: readonly string[];
    readonly settingsWarnings?: readonly SettingsWarning[];
    readonly consentRequired: boolean;
    readonly settings: Readonly<Record<string, SettingValue>>;
    readonly settingsSchema: WidgetSettingsSchema | null;
    readonly deps: DependencyView;
    readonly tier: string;
    readonly screenshots?: readonly {
        readonly url?: string | null;
        readonly sha?: string | null;
        readonly w?: number | null;
        readonly h?: number | null;
        readonly source?: 'author' | 'captured' | null;
        readonly surface?: string | null;
        readonly caption?: string | null;
    }[];
    readonly surfaces: CplugSurfaces;
    readonly missing: readonly string[];
    readonly heldReason: string | null;
    readonly storageBytes: number | null;
    readonly thirdParty: boolean;
    readonly unverified: boolean;
    readonly changedFiles: readonly string[];
    readonly publisher: string | null;
    readonly installKey?: string | null;
    readonly unrenderedSurfaces?: readonly string[];
    readonly declared?: { readonly routes: readonly string[]; readonly tools: readonly string[] };
    readonly views?: readonly CplugViewRow[];
    readonly page?: { readonly menu: string; readonly main: string } | null;
    readonly pageProblem?: string | null;
    readonly tools: readonly string[];
    readonly pluginKind?: string;
    readonly trustTier?: string;
    readonly trustBadge?: string | null;
    readonly scope?: string;
    readonly projectPath?: string | null;
    readonly runtimePaused?: boolean;
    readonly runtimeActive?: boolean;
    readonly secretsStatus?: Readonly<Record<string, CplugSecretStatus>>;
    readonly watchdog?: CplugWatchdog | null;
    readonly devLease?: CplugDevLease | null;
    readonly gitSource?: CplugGitSource | null;
    readonly installId?: string | null;
    readonly itemId?: string | null;
    readonly declarativeWidget?: DeclarativeWidgetDecl | null;
    readonly grantedUiSlots?: readonly string[];
    readonly uiSlotGrants?: readonly string[];
    readonly services?: CplugServicesDecl;
    readonly events?: CplugEventsDecl;
    readonly uiSlots?: readonly string[];
    readonly uiContribute?: Readonly<Record<string, readonly Readonly<Record<string, unknown>>[]>>;
    readonly commands?: readonly CplugCommandDecl[];
    readonly chords?: readonly CplugChordDecl[];
    readonly sessionRowActions?: readonly Readonly<Record<string, unknown>>[];
    readonly sessionBadges?: readonly unknown[];
    readonly terminalToolbar?: readonly Readonly<Record<string, unknown>>[];
    readonly projectPanels?: readonly Readonly<Record<string, unknown>>[];
    readonly channels?: readonly CplugChannelDecl[];
    readonly harnesses?: readonly string[];
    readonly popout?: boolean | Readonly<Record<string, unknown>> | readonly Readonly<Record<string, unknown>>[] | null;
    readonly revoked?: boolean;
    readonly revocationReason?: string | null;
    readonly revokedSince?: string | null;
    readonly reviewVerdict?: string | null;
    readonly flagged?: boolean;
}

export function needsTick(risk: PermissionRisk): boolean {
    return risk === 'medium' || risk === 'high';
}

export function permissionLabel(permission: string, t: Translate): string {
    const prefixed = /^(network_hosts\.write|network_hosts|lan_hosts\.write|lan_hosts|ai_features|hooks\.inbound|services|events):(.+)$/.exec(permission);
    if (prefixed) return t(`plugins.page.permission.${prefixed[1]!.replace(/\./g, '_')}`, { name: prefixed[2]! });
    return t(permissionKey(permission));
}

export function warningText(warning: CplugWarning, t: Translate): string {
    if (warning.code === 'unrestricted') return t('plugins.page.warning.unrestricted');
    return t(`plugins.page.warning.${warning.code}`, { reads: permissionLabel(warning.reads ?? '', t), host: warning.host ?? '' });
}

export function permissionKey(permission: string): string {
    return `plugins.page.permission.${permission.replace(/[.:\s]+/g, '_')}`;
}

export function isCplugItemId(id: string): boolean {
    return id.startsWith(CPLUG_ITEM_PREFIX);
}

export function cplugTags(row: CplugRow, t: Translate): string[] {
    const tags = row.tier ? [t(`plugins.page.tier.${row.tier}`)] : [];
    for (const key of TAGGED_SURFACES) {
        const value = row.surfaces?.[key];
        if (value === true || (Array.isArray(value) && value.length > 0)) tags.push(t(`plugins.page.surface.${key}`));
    }
    return tags;
}

function pluginNameKey(id: string, nameKeys?: ReadonlyMap<string, string>): string {
    return nameKeys?.get(id) || pluginsStore.rowOf(id)?.name_key || `cplug.${id}.name`;
}

export function dependencyView(row: CplugRow, t: Translate, nameKeys?: ReadonlyMap<string, string>): DependencyView {
    const d = row.dependencies ?? {};
    const needs: NeedRow[] = [
        ...(d.plugins ?? []).map((p): NeedRow => ({
            kind: 'plugin', id: p.id, label: t(pluginNameKey(p.id, nameKeys)), status: p.status === 'on' ? 'ok' : p.status === 'off' ? 'off' : 'missing',
        })),
        ...(d.core ?? []).map((c): NeedRow => ({ kind: 'core', id: c.id, label: t(`plugins.page.core.${c.id}`), status: c.available ? 'ok' : 'missing' })),
    ];
    if (d.min_app_version) {
        needs.push({
            kind: 'version', id: 'min_app_version', label: t('plugins.page.needs.version', { version: d.min_app_version.need }),
            status: d.min_app_version.met ? 'ok' : 'missing',
        });
    }
    return {
        needs,
        neededBy: (d.needed_by ?? []).map((n) => ({ id: n.id, label: t(pluginNameKey(n.id, nameKeys)), enabled: n.enabled })),
        enabledDependents: (d.enabled_dependents ?? []).map((id) => t(pluginNameKey(id, nameKeys))),
    };
}

export function toCplugItem(row: CplugRow, t: Translate, nameKeys?: ReadonlyMap<string, string>): CplugItem {
    const removed = row.state === 'removed';
    const isAgentPlugin = row.kind === 'agent-plugin' || row.runtime === 'agent-plugin';
    const noSwitch = removed || row.tier === 'core' || isAgentPlugin;
    const thirdParty = row.runtime === 'sidecar';
    const literalCopy = thirdParty || isAgentPlugin;
    const rev = revocationOfItem(row as unknown as Record<string, unknown>);
    const detailText = typeof row.detail === 'string' ? row.detail.trim() : '';
    const heldRevoked = detailText.toLowerCase() === 'revoked' || detailText.toLowerCase().startsWith('revoked:');
    const revoked = rev.revoked || heldRevoked;
    return {
        id: `${CPLUG_ITEM_PREFIX}${row.id}`,
        kind: 'cplug',
        cplugId: row.id,
        name: literalCopy ? (row.name || row.id) : row.name_key ? t(row.name_key) : row.id,
        brief: literalCopy ? row.description || null : row.description_key ? t(row.description_key) : null,
        meta: row.version ?? null,
        marks: [],
        status: row.state === 'needs_approval' ? { label: t('plugins.page.card.waiting'), tone: 'warn' } : removed ? { label: t('plugins.page.state.removed'), tone: 'off' } : undefined,
        icon: row.icon && row.icon in icons ? row.icon : 'plug',
        iconUrl: typeof row.icon_url === 'string' && row.icon_url ? row.icon_url : undefined,
        imagePath: row.preview ?? undefined,
        screenshots: Array.isArray(row.screenshots) && row.screenshots.length > 0
            ? row.screenshots
            : row.preview
              ? [{ url: row.preview, source: 'author' as const }]
              : [],
        tags: cplugTags(row, t),
        byline: literalCopy ? (row.publisher ? t('plugins.page.byline', { name: row.publisher }) : null) : row.author ? t('plugins.page.byline', { name: row.author }) : null,
        enabled: noSwitch ? null : row.enabled === true,
        version: row.version ?? '',
        asks: (row.permissions?.app ?? []).map((p) => permissionLabel(p, t)),
        state: row.state,
        blockedBy: literalCopy ? [] : (row.blocked_by ?? []).map((id) => t(pluginNameKey(id, nameKeys))),
        permissions: (row.permissions?.app ?? []).map((name) => ({
            name,
            label: permissionLabel(name, t),
            risk: (row.risks?.[name] as PermissionRisk | undefined) ?? 'high',
            reason: row.reasons?.[name] ?? '',
            granted: (row.grants?.app ?? []).includes(name),
        })),
        warnings: (row.warnings ?? []).map((w) => warningText(w, t)),
        settingsWarnings: row.settings_warnings ?? [],
        consentRequired: row.consent_required === true,
        settings: row.settings ?? {},
        settingsSchema: row.settings_schema && Object.keys(row.settings_schema.fields ?? {}).length > 0 ? row.settings_schema : null,
        deps: literalCopy ? { needs: [], neededBy: [], enabledDependents: [] } : dependencyView(row, t, nameKeys),
        tier: row.tier ?? '',
        surfaces: row.surfaces ?? {},
        missing: row.needs ?? (row.permissions?.app ?? []).filter((p) => !(row.grants?.app ?? []).includes(p)),
        heldReason: typeof row.detail === 'string' && row.detail !== '' ? row.detail : null,
        storageBytes: typeof row.storage_bytes === 'number' ? row.storage_bytes : null,
        thirdParty,
        unverified: row.unverified === true,
        changedFiles: row.unverified === true ? (row.changed_files ?? []) : [],
        publisher: literalCopy ? (row.publisher ?? null) : null,
        installKey: thirdParty ? (row.install_key ?? null) : null,
        unrenderedSurfaces: thirdParty ? (row.unrendered_surfaces ?? []) : undefined,
        declared: thirdParty ? { routes: row.routes ?? [], tools: row.declared_tools ?? [] } : undefined,
        views: thirdParty || (row.views?.length ?? 0) > 0 ? (row.views ?? []) : undefined,
        page: thirdParty ? (row.page ?? null) : undefined,
        pageProblem: thirdParty && row.page_problem ? row.page_problem : null,
        tools: thirdParty ? (row.tools ?? []) : [],
        ...(row.kind !== undefined ? { pluginKind: row.kind } : isAgentPlugin ? { pluginKind: 'agent-plugin' } : {}),
        ...(row.trust_tier !== undefined ? { trustTier: row.trust_tier } : {}),
        ...(row.trust_badge !== undefined ? { trustBadge: row.trust_badge } : {}),
        ...(row.scope !== undefined ? { scope: row.scope } : {}),
        ...(row.project_path !== undefined ? { projectPath: row.project_path } : {}),
        ...(row.runtime_paused !== undefined ? { runtimePaused: row.runtime_paused } : {}),
        ...(row.runtime_active !== undefined ? { runtimeActive: row.runtime_active } : {}),
        ...(row.secrets_status !== undefined ? { secretsStatus: row.secrets_status } : {}),
        ...(row.watchdog !== undefined ? { watchdog: row.watchdog } : {}),
        ...(row.dev_lease !== undefined ? { devLease: row.dev_lease } : {}),
        ...(row.git_source !== undefined ? { gitSource: row.git_source } : {}),
        ...(row.install_id !== undefined ? { installId: row.install_id } : {}),
        ...(row.item_id !== undefined ? { itemId: row.item_id } : {}),
        ...(row.declarative_widget !== undefined
            ? {
                  declarativeWidget:
                      row.declarative_widget && typeof row.declarative_widget === 'object'
                          ? (row.declarative_widget as DeclarativeWidgetDecl)
                          : null,
              }
            : {}),
        ...(row.granted_ui_slots !== undefined ? { grantedUiSlots: row.granted_ui_slots } : {}),
        ...(row.grants?.ui_slots !== undefined ? { uiSlotGrants: row.grants.ui_slots } : {}),
        ...(row.services !== undefined ? { services: row.services } : {}),
        ...(row.events !== undefined ? { events: row.events } : {}),
        ...(row.ui_slots !== undefined ? { uiSlots: row.ui_slots } : {}),
        ...(row.ui_contribute !== undefined ? { uiContribute: row.ui_contribute } : {}),
        ...(row.commands !== undefined ? { commands: row.commands } : {}),
        ...(row.chords !== undefined ? { chords: row.chords } : {}),
        ...(row.session_row_actions !== undefined ? { sessionRowActions: row.session_row_actions } : {}),
        ...(row.session_badges !== undefined ? { sessionBadges: row.session_badges } : {}),
        ...(row.terminal_toolbar !== undefined ? { terminalToolbar: row.terminal_toolbar } : {}),
        ...(row.project_panels !== undefined ? { projectPanels: row.project_panels } : {}),
        ...(row.channels !== undefined ? { channels: row.channels } : {}),
        ...(row.harnesses !== undefined ? { harnesses: row.harnesses } : {}),
        ...(row.popout !== undefined ? { popout: row.popout } : {}),
        ...(revoked ? { revoked: true } : {}),
        ...(rev.reason !== null ? { revocationReason: rev.reason } : {}),
        ...(rev.since !== null ? { revokedSince: rev.since } : {}),
        ...(row.review_verdict !== undefined ? { reviewVerdict: row.review_verdict } : {}),
        ...(row.flagged !== undefined ? { flagged: row.flagged } : {}),
    };
}

export async function listCplugItems(
    t: Translate,
    fetcher: typeof authFetch = authFetch,
    includeAgentPlugins = true,
): Promise<CplugItem[]> {
    if (fetcher === authFetch) {
        const ok = await pluginsStore.refresh({ allowSignedOut: true, includeAgentPlugins });
        if (!ok) {
            throw new Error(pluginsStore.error || t(MANAGER_KEYS.errorTitle));
        }
        const rows = includeAgentPlugins
            ? pluginsStore.rows
            : pluginsStore.rows.filter((row) => row.kind !== 'agent-plugin' && row.runtime !== 'agent-plugin');
        const nameKeys = new Map<string, string>();
        for (const row of pluginsStore.rows) if (row.name_key) nameKeys.set(row.id, row.name_key);
        return rows.map((row) => toCplugItem(row, t, nameKeys));
    }
    const route = includeAgentPlugins ? CPLUGS_WITH_AGENT_PLUGINS_ROUTE : CPLUGS_ROUTE;
    const body = await fetcher<{ cplugs: CplugRow[] }>(route);
    const rows = body?.cplugs ?? [];
    const nameKeys = new Map<string, string>();
    for (const row of rows) if (row.name_key) nameKeys.set(row.id, row.name_key);
    return rows.map((row) => toCplugItem(row, t, nameKeys));
}

interface DependencyRefusalBody {
    readonly code: string;
    readonly unmet?: { readonly min_app_version?: { readonly need: string; readonly have: string }; readonly core?: readonly string[] };
    readonly dependents?: readonly string[];
}

function refusalOf(error: unknown): DependencyRefusalBody | null {
    if (!(error instanceof ApiError) || error.status !== 409) return null;
    const detail = (error.payload as { detail?: unknown } | null)?.detail;
    return detail && typeof detail === 'object' && typeof (detail as { code?: unknown }).code === 'string' ? (detail as DependencyRefusalBody) : null;
}

export function dependencyRefusal(error: unknown, t: Translate): Error {
    const refusal = refusalOf(error);
    if (refusal?.code === 'requirements_unmet') {
        const parts = [
            ...(refusal.unmet?.core ?? []).map((id) => t('plugins.page.refused.core', { name: t(`plugins.page.core.${id}`) })),
            ...(refusal.unmet?.min_app_version ? [t('plugins.page.refused.version', refusal.unmet.min_app_version)] : []),
        ];
        return new Error(t('plugins.page.refused.on', { why: parts.join('; ') }));
    }
    if (refusal?.code === 'has_dependents') {
        return new Error(t('plugins.page.refused.off', { names: (refusal.dependents ?? []).map((id) => t(pluginNameKey(id))).join(', ') }));
    }
    return error instanceof Error ? error : new Error(String(error));
}

export async function setCplugEnabled(
    itemId: string,
    enabled: boolean,
    t: Translate,
    fetcher: typeof authFetch = authFetch,
    onChanged: () => Promise<void> = refreshEnablement,
    confirmDependents = false,
): Promise<CplugItem> {
    const path = `${CPLUGS_ROUTE}/${encodeURIComponent(itemId.slice(CPLUG_ITEM_PREFIX.length))}`;
    const current = await fetcher<CplugRow>(path);
    const declaredSlots = current.ui_contribute ? Object.keys(current.ui_contribute) : [];
    const body: Record<string, unknown> = { revision: current.revision ?? 0, enabled };
    if (!enabled && confirmDependents) body.confirm_dependents = true;
    if (enabled) {
        body.grants = {
            app: [...(current.permissions?.app ?? [])],
            ...(declaredSlots.length > 0 ? { ui_slots: declaredSlots } : {}),
        };
    }
    if (enabled && current.consent_required) {
        const sheet = await fetcher<CplugSheet>(`${path}/sheet`);
        if (
            sheet.permissions.some((p) => needsTick(p.risk) && !p.granted) ||
            (sheet.ui_slots ?? []).some((s) => (s.needs_tick || needsTick(s.risk)) && !s.granted)
        ) {
            throw new Error(t('plugins.page.sheet.tick_first'));
        }
        const sheetSlots = (sheet.ui_slots ?? []).map((s) => s.slot);
        const uiSlots = sheetSlots.length > 0 ? sheetSlots : declaredSlots;
        if (uiSlots.length > 0) {
            body.grants = { app: [...(current.permissions?.app ?? [])], ui_slots: uiSlots };
        }
        body.consent = {
            digest: sheet.digest,
            body_sha: sheet.body_sha,
            grants_sha: sheet.grants_sha,
            ticks: [],
            ...(sheet.ui_slots_sha !== undefined ? { ui_slots_sha: sheet.ui_slots_sha, slot_ticks: [] } : {}),
        };
    }
    let row: CplugRow;
    try {
        row = await fetcher<CplugRow>(path, { method: 'PUT', body: JSON.stringify(body) });
    } catch (error) {
        throw dependencyRefusal(error, t);
    }
    await onChanged();
    return toCplugItem(row, t);
}

export async function setCplugSetting(
    cplugId: string,
    key: string,
    value: SettingValue,
    t: Translate,
    fetcher: typeof authFetch = authFetch,
    onChanged: () => Promise<void> = refreshEnablement,
): Promise<CplugItem> {
    const path = `${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}`;
    let row: CplugRow | undefined;
    for (let attempt = 0; attempt < 2 && !row; attempt += 1) {
        const current = await fetcher<CplugRow>(path);
        try {
            row = await fetcher<CplugRow>(path, { method: 'PUT', body: JSON.stringify({ revision: current.revision ?? 0, settings: { [key]: value } }) });
        } catch (error) {
            if (attempt === 1 || !(error instanceof ApiError) || error.status !== 409) throw error;
        }
    }
    await onChanged();
    return toCplugItem(row!, t);
}

export async function listActivity(cplugId: string, fetcher: typeof authFetch = authFetch): Promise<ActivityRow[]> {
    const body = await fetcher<{ activity: ActivityRow[] }>(`${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}/activity?limit=50`);
    return body?.activity ?? [];
}

export interface CplugsAdapter extends ManagerAdapter {
    confirmDependents(itemId: string): void;
}

export function createCplugsAdapter(
    t: Translate,
    fetcher: typeof authFetch = authFetch,
    onChanged: () => Promise<void> = refreshEnablement,
): CplugsAdapter {
    const confirmed = new Set<string>();
    return {
        list: (): Promise<readonly ManagerItem[]> => listCplugItems(t, fetcher),
        setEnabled: (id: string, enabled: boolean): Promise<ManagerItem> => {
            const confirm = confirmed.delete(id);
            return setCplugEnabled(id, enabled, t, fetcher, onChanged, confirm);
        },
        confirmDependents: (itemId: string): void => void confirmed.add(itemId),
    };
}

/* the detail pane the plugins page */
import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { icons } from '../../opscenter/ui/icons';
import { refreshEnablement } from '../../cplugs/host/enablement.svelte';
import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import type { SettingValue } from '../item-settings/api';

export const CPLUGS_ROUTE = '/cplugs';
export const CPLUG_ITEM_PREFIX = 'cplug:';

export interface CplugViewRow {
    readonly name: string;
    readonly surfaces: readonly string[];
    readonly fits?: { readonly sizes?: readonly string[]; readonly min?: { readonly w?: number; readonly h?: number }; readonly anySize?: boolean } | null;
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

export interface CplugRow {
    readonly id: string;
    readonly name_key?: string;
    readonly description_key?: string;
    readonly version?: string;
    readonly tier?: string;
    readonly icon?: string;
    readonly author?: string;
    readonly surfaces?: CplugSurfaces;
    readonly enabled: boolean;
    readonly state: string;
    readonly blocked_by?: readonly string[];
    readonly permissions?: { readonly app?: readonly string[] };
    readonly grants?: { readonly app?: readonly string[] };
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
    readonly runtime?: 'sidecar' | 'compiled';
    readonly name?: string | null;
    readonly description?: string | null;
    readonly publisher?: string | null;
    readonly tools?: readonly string[] | null;
    readonly routes?: readonly string[] | null;
    readonly declared_tools?: readonly string[] | null;
    readonly install_key?: string | null;
    readonly views?: readonly CplugViewRow[] | null;
    readonly page?: { readonly menu: string; readonly main: string } | null;
    readonly page_problem?: string | null;
    readonly topics?: readonly string[] | null;
    readonly preview?: string | null;
    readonly unverified?: boolean;
    readonly changed_files?: readonly string[];
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

export type PermissionRisk = 'low' | 'medium' | 'high' | 'never';

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
    readonly permissions: readonly { readonly name: string; readonly risk: PermissionRisk; readonly granted: boolean }[];
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
    readonly surfaces: CplugSurfaces;
    readonly missing: readonly string[];
    readonly heldReason: string | null;
    readonly storageBytes: number | null;
    readonly thirdParty: boolean;
    readonly unverified: boolean;
    readonly changedFiles: readonly string[];
    readonly publisher: string | null;
    readonly installKey?: string | null;
    readonly declared?: { readonly routes: readonly string[]; readonly tools: readonly string[] };
    readonly views?: readonly CplugViewRow[];
    readonly page?: { readonly menu: string; readonly main: string } | null;
    readonly pageProblem?: string | null;
    readonly tools: readonly string[];
}

export function needsTick(risk: PermissionRisk): boolean {
    return risk === 'medium' || risk === 'high';
}

export function permissionLabel(permission: string, t: Translate): string {
    const prefixed = /^(network_hosts\.write|network_hosts|lan_hosts\.write|lan_hosts|ai_features):(.+)$/.exec(permission);
    if (prefixed) return t(`plugins.page.permission.${prefixed[1]!.replace(/\./g, '_')}`, { name: prefixed[2]! });
    return t(permissionKey(permission));
}

export function warningText(warning: CplugWarning, t: Translate): string {
    if (warning.code === 'unrestricted') return t('plugins.page.warning.unrestricted');
    return t(`plugins.page.warning.${warning.code}`, { reads: permissionLabel(warning.reads ?? '', t), host: warning.host ?? '' });
}

export function permissionKey(permission: string): string {
    return `plugins.page.permission.${permission.replace(/\./g, '_')}`;
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

export function dependencyView(row: CplugRow, t: Translate): DependencyView {
    const d = row.dependencies ?? {};
    const needs: NeedRow[] = [
        ...(d.plugins ?? []).map((p): NeedRow => ({
            kind: 'plugin', id: p.id, label: t(`cplug.${p.id}.name`), status: p.status === 'on' ? 'ok' : p.status === 'off' ? 'off' : 'missing',
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
        neededBy: (d.needed_by ?? []).map((n) => ({ id: n.id, label: t(`cplug.${n.id}.name`), enabled: n.enabled })),
        enabledDependents: (d.enabled_dependents ?? []).map((id) => t(`cplug.${id}.name`)),
    };
}

export function toCplugItem(row: CplugRow, t: Translate): CplugItem {
    const removed = row.state === 'removed';
    const noSwitch = removed || row.tier === 'core';
    const thirdParty = row.runtime === 'sidecar';
    return {
        id: `${CPLUG_ITEM_PREFIX}${row.id}`,
        kind: 'cplug',
        cplugId: row.id,
        name: thirdParty ? (row.name || row.id) : row.name_key ? t(row.name_key) : row.id,
        brief: thirdParty ? row.description || null : row.description_key ? t(row.description_key) : null,
        meta: row.version ?? null,
        marks: [],
        status: row.state === 'needs_approval' ? { label: t('plugins.page.card.waiting'), tone: 'warn' } : removed ? { label: t('plugins.page.state.removed'), tone: 'off' } : undefined,
        icon: row.icon && row.icon in icons ? row.icon : 'plug',
        imagePath: row.preview ?? undefined,
        tags: cplugTags(row, t),
        byline: thirdParty ? (row.publisher ? t('plugins.page.byline', { name: row.publisher }) : null) : row.author ? t('plugins.page.byline', { name: row.author }) : null,
        enabled: noSwitch ? null : row.enabled === true,
        version: row.version ?? '',
        asks: (row.permissions?.app ?? []).map((p) => permissionLabel(p, t)),
        state: row.state,
        blockedBy: thirdParty ? [] : (row.blocked_by ?? []).map((id) => t(`cplug.${id}.name`)),
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
        deps: thirdParty ? { needs: [], neededBy: [], enabledDependents: [] } : dependencyView(row, t),
        tier: row.tier ?? '',
        surfaces: row.surfaces ?? {},
        missing: row.needs ?? (row.permissions?.app ?? []).filter((p) => !(row.grants?.app ?? []).includes(p)),
        heldReason: typeof row.detail === 'string' && row.detail !== '' ? row.detail : null,
        storageBytes: typeof row.storage_bytes === 'number' ? row.storage_bytes : null,
        thirdParty,
        unverified: row.unverified === true,
        changedFiles: row.unverified === true ? (row.changed_files ?? []) : [],
        publisher: thirdParty ? (row.publisher ?? null) : null,
        installKey: thirdParty ? (row.install_key ?? null) : null,
        declared: thirdParty ? { routes: row.routes ?? [], tools: row.declared_tools ?? [] } : undefined,
        views: thirdParty ? (row.views ?? []) : undefined,
        page: thirdParty ? (row.page ?? null) : undefined,
        pageProblem: thirdParty && row.page_problem ? row.page_problem : null,
        tools: thirdParty ? (row.tools ?? []) : [],
    };
}

export async function listCplugItems(t: Translate, fetcher: typeof authFetch = authFetch): Promise<CplugItem[]> {
    const body = await fetcher<{ cplugs: CplugRow[] }>(CPLUGS_ROUTE);
    return (body?.cplugs ?? []).map((row) => toCplugItem(row, t));
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
        return new Error(t('plugins.page.refused.off', { names: (refusal.dependents ?? []).map((id) => t(`cplug.${id}.name`)).join(', ') }));
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
    const body: Record<string, unknown> = { revision: current.revision ?? 0, enabled };
    if (!enabled && confirmDependents) body.confirm_dependents = true;
    if (enabled) body.grants = { app: [...(current.permissions?.app ?? [])] };
    if (enabled && current.consent_required) {
        const sheet = await fetcher<CplugSheet>(`${path}/sheet`);
        if (sheet.permissions.some((p) => needsTick(p.risk) && !p.granted)) throw new Error(t('plugins.page.sheet.tick_first'));
        body.consent = { digest: sheet.digest, body_sha: sheet.body_sha, grants_sha: sheet.grants_sha, ticks: [] };
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

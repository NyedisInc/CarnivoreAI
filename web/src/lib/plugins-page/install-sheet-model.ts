import type { CardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import type { InstallConsent, InstallPreview, InstallRequest, InstallScope } from '../catalog/types';
import { ApiError } from '../../opscenter/api/auth.svelte';
import {
    dependencyRefusal,
    needsTick,
    permissionLabel,
    warningText,
    type CplugEventsDecl,
    type CplugItem,
    type CplugRow,
    type CplugSecretStatus,
    type CplugServicesDecl,
    type CplugSheet,
    type CplugUiSlotRow,
    type CplugWarning,
    type PermissionRisk,
    type PermissionRow,
} from './cplugs-adapter';
import {
    errorMessageOf,
    type GithubInstallRequest,
    type GithubInstallResponse,
    type GithubPreviewRequest,
    type GithubPreviewResponse,
    type PluginUpdateRequest,
} from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';

export interface InstallSheetStore {
    previewGithub(body: GithubPreviewRequest): Promise<GithubPreviewResponse>;
    installGithub(body: GithubInstallRequest): Promise<GithubInstallResponse>;
    updatePlugin(id: string, body: PluginUpdateRequest): Promise<CplugRow>;
    refresh?(opts?: { readonly force?: boolean; readonly allowSignedOut?: boolean }): Promise<boolean>;
}

export interface CapabilityTool {
    readonly name: string;
    readonly gate?: string;
    readonly description?: string;
    readonly input_schema?: unknown;
}

export interface CapabilityHost {
    readonly host: string;
    readonly reason?: string;
    readonly methods?: readonly string[];
    readonly paths?: readonly string[];
    readonly kind?: 'network' | 'lan';
}

export interface SecretDescriptor {
    readonly name: string;
    readonly label: string;
    readonly hosts: readonly string[];
}

export interface GroupedCapabilities {
    readonly low: readonly PermissionRow[];
    readonly medium: readonly PermissionRow[];
    readonly high: readonly PermissionRow[];
    readonly never: readonly PermissionRow[];
    readonly pendingTicks: readonly PermissionRow[];
    readonly hasNever: boolean;
}

const KNOWN_ERROR_KEYS: Readonly<Record<string, string>> = {
    safe_mode_forced: 'plugins.page.install_sheet.error.safe_mode_forced',
    catalog_id_hijack: 'plugins.page.install_sheet.error.catalog_id_hijack',
    name_taken: 'plugins.page.install_sheet.error.name_taken',
    tick_missing: 'plugins.page.install_sheet.error.tick_missing',
    secret_invalid: 'plugins.page.install_sheet.error.secret_invalid',
    secret_empty: 'plugins.page.install_sheet.error.secret_invalid',
    secret_too_long: 'plugins.page.install_sheet.error.secret_invalid',
    secret_chars: 'plugins.page.install_sheet.error.secret_invalid',
    secret_unknown: 'plugins.page.install_sheet.error.secret_invalid',
    keychain_refused: 'plugins.page.install_sheet.error.secret_invalid',
    secrets_unreadable: 'plugins.page.install_sheet.error.secret_invalid',
    secrets_unwritable: 'plugins.page.install_sheet.error.secret_invalid',
    git_failed: 'plugins.page.install_sheet.error.git_failed',
    git_unavailable: 'plugins.page.install_sheet.error.git_failed',
    git_timeout: 'plugins.page.install_sheet.error.git_failed',
    git_url_refused: 'plugins.page.install_sheet.error.git_failed',
    ref_invalid: 'plugins.page.install_sheet.error.git_failed',
    subdir_invalid: 'plugins.page.install_sheet.error.git_failed',
    consent_stale: 'plugins.page.install_sheet.error.consent_stale',
    consent_mismatch: 'plugins.page.install_sheet.error.consent_mismatch',
    reason_missing: 'plugins.page.install_sheet.error.reason_missing',
    grant_never: 'plugins.page.install_sheet.error.grant_never',
    scope_unsupported: 'plugins.page.install_sheet.error.scope_unsupported',
    cplug_flagged_ack_required: 'plugins.page.install_sheet.error.cplug_flagged_ack_required',
    permission_widened: 'plugins.page.install_sheet.error.permission_widened',
    commit_sha_mismatch: 'plugins.page.install_sheet.error.commit_sha_mismatch',
    item_revoked: 'plugins.page.install_sheet.error.item_revoked',
};

const SAFE_MODE_DETAIL_RE = /^disabled\s+\(safe\s+mode\)$/i;

export function isRuntimeDisabledDetail(detail: string | null | undefined): boolean {
    if (!detail) return false;
    return detail === 'third_party_off' || SAFE_MODE_DETAIL_RE.test(detail);
}

export function extractErrorCode(err: unknown): string | null {
    if (!err || typeof err !== 'object') return null;
    if (err instanceof ApiError && err.code) return err.code;
    const rec = err as {
        code?: unknown;
        payload?: unknown;
        body?: unknown;
        detail?: unknown;
    };
    const candidates = [
        rec.code,
        (rec.payload as { code?: unknown } | undefined)?.code,
        (rec.payload as { detail?: { code?: unknown } } | undefined)?.detail?.code,
        (rec.body as { code?: unknown } | undefined)?.code,
        (rec.body as { detail?: { code?: unknown } } | undefined)?.detail?.code,
        (rec.detail as { code?: unknown } | undefined)?.code,
    ];
    for (const candidate of candidates) {
        if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
    return null;
}

export interface UnmetRequirements {
    readonly min_app_version?: { readonly need: string; readonly have: string };
    readonly core?: readonly string[];
}

export function formatUnmetRequirements(unmet: UnmetRequirements | null | undefined, t: Translate): string | null {
    if (!unmet) return null;
    const parts = [
        ...(unmet.core ?? []).map((id) => t('plugins.page.refused.core', { name: t(`plugins.page.core.${id}`) })),
        ...(unmet.min_app_version ? [t('plugins.page.refused.version', unmet.min_app_version)] : []),
    ];
    if (parts.length === 0) return null;
    return t('plugins.page.refused.on', { why: parts.join('; ') });
}

export function installErrorMessage(err: unknown, t: Translate): string {
    const code = extractErrorCode(err);
    if (code === 'requirements_unmet' || code === 'has_dependents') {
        const mapped = dependencyRefusal(err, t);
        if (mapped.message && mapped.message !== errorMessageOf(err)) return mapped.message;
        const payload = err && typeof err === 'object' ? (err as { payload?: { detail?: { unmet?: UnmetRequirements } }; body?: { detail?: { unmet?: UnmetRequirements } } }) : null;
        const unmet = payload?.payload?.detail?.unmet ?? payload?.body?.detail?.unmet;
        const formatted = formatUnmetRequirements(unmet, t);
        if (formatted) return formatted;
    }
    const key = code ? KNOWN_ERROR_KEYS[code] : undefined;
    if (key) return t(key);
    return errorMessageOf(err);
}

export function normalizeRisk(raw: string | undefined): PermissionRisk {
    if (raw === 'low' || raw === 'medium' || raw === 'high' || raw === 'never') return raw;
    return 'high';
}

export function groupCapabilities(permissions: readonly PermissionRow[]): GroupedCapabilities {
    const low: PermissionRow[] = [];
    const medium: PermissionRow[] = [];
    const high: PermissionRow[] = [];
    const never: PermissionRow[] = [];
    const pendingTicks: PermissionRow[] = [];

    for (const perm of permissions) {
        if (perm.risk === 'low') {
            low.push(perm);
        } else if (perm.risk === 'medium') {
            medium.push(perm);
            if (!perm.granted && needsTick(perm.risk)) pendingTicks.push(perm);
        } else if (perm.risk === 'never') {
            never.push(perm);
        } else {
            high.push(perm);
            if (!perm.granted && needsTick(perm.risk)) pendingTicks.push(perm);
        }
    }

    return {
        low,
        medium,
        high,
        never,
        pendingTicks,
        hasNever: never.length > 0,
    };
}

export function formatWarnings(warnings: readonly (CplugWarning | string)[] | undefined, t: Translate): string[] {
    if (!Array.isArray(warnings)) return [];
    return warnings
        .map((w) => (typeof w === 'string' ? w : warningText(w, t)))
        .filter((line) => line.length > 0);
}

export function toPermissionRows(
    raw: readonly { readonly name: string; readonly risk?: string; readonly reason?: string; readonly granted?: boolean }[] | undefined,
    t: Translate,
): PermissionRow[] {
    if (!Array.isArray(raw)) return [];
    return raw.map((p) => ({
        name: p.name,
        label: permissionLabel(p.name, t),
        risk: normalizeRisk(p.risk),
        reason: p.reason ?? '',
        granted: p.granted === true,
    }));
}

export function secretsForItem(
    item: CplugItem | null | undefined,
    explicitSecrets?: readonly SecretDescriptor[],
): SecretDescriptor[] {
    if (explicitSecrets && explicitSecrets.length > 0) return [...explicitSecrets];
    const map: Readonly<Record<string, CplugSecretStatus>> | undefined = item?.secretsStatus;
    if (!map) return [];
    return Object.keys(map).map((name) => ({
        name,
        label: name,
        hosts: [],
    }));
}

export function nonEmptySecretsMap(values: Readonly<Record<string, string>>): Record<string, string> | undefined {
    const out: Record<string, string> = {};
    let count = 0;
    for (const [k, v] of Object.entries(values)) {
        if (typeof v === 'string' && v.length > 0) {
            out[k] = v;
            count += 1;
        }
    }
    return count > 0 ? out : undefined;
}

export function buildGithubConsent(
    preview: GithubPreviewResponse,
    ticks: readonly string[],
    slotTicks: readonly string[] = [],
): Record<string, unknown> | undefined {
    const sheet = preview.consent_sheet as {
        readonly digest?: string;
        readonly body_sha?: string;
        readonly grants_sha?: string;
        readonly ui_slots?: readonly CplugUiSlotRow[];
        readonly ui_slots_sha?: string;
    } | undefined;
    const digest = sheet?.digest ?? preview.digest ?? preview.code_sha256;
    const bodySha = sheet?.body_sha ?? preview.body_sha;
    if (!digest || !bodySha) return undefined;
    if (preview.kind === 'agent-plugin') {
        return { digest, body_sha: bodySha };
    }
    const hasUiSlots = (sheet?.ui_slots?.length ?? 0) > 0 || slotTicks.length > 0;
    return {
        digest,
        body_sha: bodySha,
        ...(sheet?.grants_sha !== undefined ? { grants_sha: sheet.grants_sha } : {}),
        ticks: [...ticks],
        ...(hasUiSlots && sheet?.ui_slots_sha !== undefined
            ? { ui_slots_sha: sheet.ui_slots_sha, slot_ticks: [...slotTicks] }
            : hasUiSlots && slotTicks.length > 0
              ? { slot_ticks: [...slotTicks] }
              : {}),
    };
}

export function buildSheetConsent(
    sheet: CplugSheet,
    ticks: readonly string[],
    slotTicks: readonly string[] = [],
): Record<string, unknown> {
    const hasUiSlots = (sheet.ui_slots?.length ?? 0) > 0 || slotTicks.length > 0;
    return {
        digest: sheet.digest,
        body_sha: sheet.body_sha,
        grants_sha: sheet.grants_sha,
        ticks: [...ticks],
        ...(hasUiSlots
            ? {
                  ...(sheet.ui_slots_sha !== undefined ? { ui_slots_sha: sheet.ui_slots_sha } : {}),
                  slot_ticks: [...slotTicks],
              }
            : {}),
    };
}

export interface SubmitInstallSheetArgs {
    readonly mode: 'github' | 'catalog' | 'enable';
    readonly enable: boolean;
    readonly source: string;
    readonly ref: string;
    readonly subdir: string;
    readonly scope: InstallScope;
    readonly projectPath: string;
    readonly showScopePicker: boolean;
    readonly showRuntimeToggle: boolean;
    readonly activateRuntime: boolean;
    readonly selectedTicks: readonly string[];
    readonly selectedSlotTicks?: readonly string[];
    readonly secretValues: Readonly<Record<string, string>>;
    readonly githubPreview: GithubPreviewResponse | null;
    readonly catalogPreview: InstallPreview | null;
    readonly enableSheet: CplugSheet | null;
    readonly item: CplugItem | null;
    readonly card: CardView | null;
    readonly host: CatalogHost | null;
    readonly store: InstallSheetStore;
    readonly loadSheet: (cplugId: string) => Promise<CplugSheet>;
    readonly cplugFlaggedAck?: boolean;
}

export interface SubmitInstallSheetResult {
    readonly id?: string;
    readonly enabled: boolean;
    readonly scope?: InstallScope;
    readonly projectPath?: string | null;
    readonly needsSlotConsent?: {
        readonly cplugId: string;
        readonly sheet: CplugSheet;
    };
}

export async function executeInstallSheetSubmit(
    args: SubmitInstallSheetArgs,
): Promise<SubmitInstallSheetResult | null> {
    const secrets = nonEmptySecretsMap(args.secretValues);
    const selectedSlotTicks = args.selectedSlotTicks ?? [];

    if (args.mode === 'github' && args.githubPreview) {
        const consent = buildGithubConsent(args.githubPreview, args.selectedTicks, selectedSlotTicks);
        const ghSheet = args.githubPreview.consent_sheet as { readonly ui_slots?: readonly CplugUiSlotRow[] } | undefined;
        const ghSlotNames = (ghSheet?.ui_slots ?? []).map((s) => s.slot);
        const declaredSlots =
            ghSlotNames.length > 0
                ? ghSlotNames
                : (args.githubPreview.declared_ui_slots ??
                  (args.githubPreview.ui_contribute ? Object.keys(args.githubPreview.ui_contribute) : []));
        const res = await args.store.installGithub({
            source: args.source.trim(),
            ...(args.ref.trim() ? { ref: args.ref.trim() } : {}),
            ...(args.subdir.trim() ? { subdir: args.subdir.trim() } : {}),
            ...(args.showScopePicker
                ? { scope: args.scope, project_path: args.scope === 'project' ? args.projectPath : null }
                : {}),
            enable: args.enable,
            activate_runtime: args.enable && args.showRuntimeToggle ? args.activateRuntime : false,
            ...(secrets ? { secrets } : {}),
            ...(declaredSlots.length > 0 && args.githubPreview.kind !== 'agent-plugin'
                ? { ui_slots: [...declaredSlots] }
                : {}),
            ...(consent ? { consent } : {}),
        });
        return {
            id: res.id,
            enabled: res.enabled,
            ...(args.showScopePicker
                ? {
                    scope: res.scope ?? args.scope,
                    projectPath: (res.project_path ?? (args.scope === 'project' ? args.projectPath : null)) || null,
                }
                : {}),
        };
    }

    if (args.mode === 'catalog' && args.card && args.host && args.catalogPreview) {
        const preview = args.catalogPreview;
        const baseConsent: (InstallConsent & Record<string, unknown>) | undefined =
            args.card.isCplug && preview.digest && preview.body_sha && preview.cplug_facts_sha
                ? {
                    digest: preview.digest,
                    body_sha: preview.body_sha,
                    scripts: true,
                    cplug_accepted: true,
                    cplug_facts_sha: preview.cplug_facts_sha,
                }
                : preview.digest && preview.body_sha
                  ? { digest: preview.digest, body_sha: preview.body_sha, scripts: true }
                  : undefined;
        const consent: InstallConsent | undefined = baseConsent
            ? args.cplugFlaggedAck
                ? ({ ...baseConsent, cplug_flagged_ack: true, acknowledge_flagged: true } as InstallConsent)
                : baseConsent
            : args.cplugFlaggedAck
              ? ({ cplug_flagged_ack: true, acknowledge_flagged: true } as unknown as InstallConsent)
              : undefined;
        const req: InstallRequest = {
            item_id: args.card.id || '',
            scope: args.showScopePicker ? args.scope : 'global',
            ...(args.showScopePicker && args.scope === 'project' ? { project_path: args.projectPath } : {}),
            ...(preview.plan_token ? { plan_token: preview.plan_token } : {}),
            ...(consent ? { consent } : {}),
        };
        const installed = await args.host.install(req);
        const cplugId =
            preview.cplug_facts?.id || args.card.name || installed.name || args.card.id?.split('/')[1] || '';

        if (args.enable && args.card.isCplug && cplugId) {
            const sheet = await args.loadSheet(cplugId);
            const selectedSlotsSet = new Set(selectedSlotTicks);
            const missingSlotTick = (sheet.ui_slots ?? []).some(
                (s) => !s.granted && (s.needs_tick || needsTick(s.risk)) && !selectedSlotsSet.has(s.slot),
            );
            if (missingSlotTick) {
                if (args.store.refresh) await args.store.refresh({ force: true, allowSignedOut: true });
                return {
                    id: cplugId,
                    enabled: false,
                    needsSlotConsent: { cplugId, sheet },
                };
            }
            const slotNames = (sheet.ui_slots ?? []).map((s) => s.slot);
            await args.store.updatePlugin(cplugId, {
                enabled: true,
                grants: {
                    app: sheet.permissions.map((p) => p.name),
                    ...(slotNames.length > 0 ? { ui_slots: slotNames } : {}),
                },
                consent: buildSheetConsent(sheet, args.selectedTicks, selectedSlotTicks),
                ...(args.showRuntimeToggle ? { activate_runtime: args.activateRuntime } : {}),
                ...(secrets ? { secrets } : {}),
            });
            return { id: cplugId, enabled: true };
        }
        if (!args.enable && args.card.isCplug && cplugId && secrets) {
            await args.store.updatePlugin(cplugId, {
                enabled: false,
                secrets,
            });
        }
        if (args.store.refresh) await args.store.refresh({ force: true, allowSignedOut: true });
        return {
            id: installed.install_id ?? (cplugId || undefined),
            enabled: args.enable && !args.card.isCplug,
            ...(args.showScopePicker
                ? {
                    scope: installed.scope ?? args.scope,
                    projectPath: (installed.project_path ?? (args.scope === 'project' ? args.projectPath : null)) || null,
                }
                : {}),
        };
    }

    if (args.mode === 'enable' && args.item) {
        const sheetSlotNames = (args.enableSheet?.ui_slots ?? []).map((s) => s.slot);
        const itemSlotNames = args.item.uiContribute ? Object.keys(args.item.uiContribute) : [];
        const slotNames = sheetSlotNames.length > 0 ? sheetSlotNames : itemSlotNames;
        const consent = args.enableSheet
            ? buildSheetConsent(args.enableSheet, args.selectedTicks, selectedSlotTicks)
            : undefined;
        const row = await args.store.updatePlugin(args.item.cplugId, {
            enabled: true,
            grants: {
                app: args.item.permissions.map((p) => p.name),
                ...(slotNames.length > 0 ? { ui_slots: slotNames } : {}),
            },
            ...(consent ? { consent } : {}),
            ...(args.showRuntimeToggle ? { activate_runtime: args.activateRuntime } : {}),
            ...(secrets ? { secrets } : {}),
        });
        return { id: row.id, enabled: row.enabled === true };
    }

    return null;
}

function buildSlotRowsFromContribute(
    contribute: Readonly<Record<string, readonly Readonly<Record<string, unknown>>[]>> | undefined,
    grantedSlots: readonly string[] = [],
): CplugUiSlotRow[] {
    if (!contribute) return [];
    const grantedSet = new Set(grantedSlots);
    return Object.entries(contribute).map(([slot, entries]) => ({
        slot,
        count: Array.isArray(entries) ? entries.length : 1,
        risk: 'medium',
        reason: '',
        granted: grantedSet.has(slot),
        needs_tick: true,
    }));
}

export function deriveSheetFacts(params: {
    readonly mode: 'github' | 'catalog' | 'enable';
    readonly githubPreview: GithubPreviewResponse | null;
    readonly catalogPreview: InstallPreview | null;
    readonly enableSheet?: CplugSheet | null;
    readonly item: CplugItem | null;
    readonly explicitSecrets?: readonly SecretDescriptor[];
    readonly t: Translate;
}): {
    readonly permissions: readonly PermissionRow[];
    readonly warnings: readonly (CplugWarning | string)[];
    readonly tools: readonly CapabilityTool[];
    readonly networkHosts: readonly CapabilityHost[];
    readonly lanHosts: readonly CapabilityHost[];
    readonly secrets: readonly SecretDescriptor[];
    readonly uiSlots: readonly CplugUiSlotRow[];
    readonly services: CplugServicesDecl | null;
    readonly events: CplugEventsDecl | null;
    readonly unmetRequirements: UnmetRequirements | null;
} {
    const { mode, githubPreview, catalogPreview, enableSheet, item, explicitSecrets, t } = params;
    const extras = (githubPreview ?? catalogPreview ?? null) as {
        readonly tools?: readonly CapabilityTool[];
        readonly network_hosts?: readonly CapabilityHost[];
        readonly lan_hosts?: readonly CapabilityHost[];
        readonly cplug_facts?: InstallPreview['cplug_facts'] & {
            readonly ui_slots?: readonly CplugUiSlotRow[];
            readonly services?: CplugServicesDecl;
            readonly events?: CplugEventsDecl;
            readonly unmet_requirements?: UnmetRequirements;
        };
    } | null;

    if (mode === 'github') {
        const lanHosts: readonly CapabilityHost[] = extras?.lan_hosts
            ? extras.lan_hosts
            : (extras?.cplug_facts?.lan_hosts ?? []).map((h) => ({
                host: h.entry,
                reason: h.reason,
                methods: h.methods,
                paths: h.paths,
            }));
        const ghSheet = githubPreview?.consent_sheet as { readonly ui_slots?: readonly CplugUiSlotRow[] } | undefined;
        const uiSlots =
            ghSheet?.ui_slots && ghSheet.ui_slots.length > 0
                ? ghSheet.ui_slots
                : buildSlotRowsFromContribute(githubPreview?.ui_contribute);
        return {
            permissions: toPermissionRows(githubPreview?.permissions, t),
            warnings: githubPreview?.warnings ?? [],
            tools: extras?.tools ?? extras?.cplug_facts?.tools ?? [],
            networkHosts: extras?.network_hosts ?? extras?.cplug_facts?.network_hosts ?? [],
            lanHosts,
            secrets: (githubPreview?.secrets ?? []).map((s) => ({
                name: s.name,
                label: s.label ?? s.name,
                hosts: s.hosts ?? [],
            })),
            uiSlots,
            services: githubPreview?.services ?? null,
            events: githubPreview?.events ?? null,
            unmetRequirements: extras?.cplug_facts?.unmet_requirements ?? null,
        };
    }

    if (mode === 'catalog') {
        const facts = extras?.cplug_facts;
        return {
            permissions: toPermissionRows(facts?.permissions, t),
            warnings: [],
            tools: facts?.tools ?? [],
            networkHosts: facts?.network_hosts ?? [],
            lanHosts: (facts?.lan_hosts ?? []).map((h) => ({
                host: h.entry,
                reason: h.reason,
                methods: h.methods,
                paths: h.paths,
            })),
            secrets: (facts?.secrets ?? []).map((s) => ({
                name: s.name,
                label: s.label ?? s.name,
                hosts: s.hosts ?? [],
            })),
            uiSlots: facts?.ui_slots ?? [],
            services: facts?.services ?? null,
            events: facts?.events ?? null,
            unmetRequirements: facts?.unmet_requirements ?? null,
        };
    }

    const toolNames = item?.tools?.length ? item.tools : (item?.declared?.tools ?? []);
    const itemPermissions =
        item?.permissions && item.permissions.length > 0
            ? item.permissions
            : toPermissionRows(enableSheet?.permissions, t);
    const uiSlots =
        enableSheet?.ui_slots && enableSheet.ui_slots.length > 0
            ? enableSheet.ui_slots
            : buildSlotRowsFromContribute(item?.uiContribute, item?.grantedUiSlots ?? item?.uiSlotGrants ?? []);
    return {
        permissions: itemPermissions,
        warnings: item?.warnings ?? [],
        tools: toolNames.map((name) => ({ name })),
        networkHosts: [],
        lanHosts: [],
        secrets: secretsForItem(item, explicitSecrets),
        uiSlots,
        services: item?.services ?? null,
        events: item?.events ?? null,
        unmetRequirements: null,
    };
}

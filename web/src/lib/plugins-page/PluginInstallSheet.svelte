
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import RadioGroup from '../base/RadioGroup.svelte';
    import Select from '../base/Select.svelte';
    import Tag from '../base/Tag.svelte';
    import type { CardView } from '../catalog/card';
    import type { CatalogHost } from '../catalog/catalog';
    import FlaggedWarningBox from '../catalog/FlaggedWarningBox.svelte';
    import { flaggedMetaFromSheet } from '../catalog/permission-diff';
    import type { InstallPreview, InstallRequest, InstallScope } from '../catalog/types';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { pluginsStore, type GithubPreviewRequest, type GithubPreviewResponse } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import CapabilityCards from './CapabilityCards.svelte';
    import { readSheet } from './cplug-grant';
    import { needsTick, toCplugItem, type CplugItem, type CplugSheet } from './cplugs-adapter';
    import GithubSourcePicker from './GithubSourcePicker.svelte';
    import InlineSecretsFields from './InlineSecretsFields.svelte';
    import {
        deriveSheetFacts,
        executeInstallSheetSubmit,
        extractErrorCode,
        formatUnmetRequirements,
        groupCapabilities,
        installErrorMessage,
        isRuntimeDisabledDetail,
        toPermissionRows,
        type InstallSheetStore,
        type SecretDescriptor,
    } from './install-sheet-model';

    interface ProjectEntry {
        readonly path: string;
        readonly name: string;
    }

    interface Props {
        open: boolean;
        mode: 'github' | 'catalog' | 'enable';
        t: Translate;
        item?: CplugItem | null;
        card?: CardView | null;
        host?: CatalogHost | null;
        projects?: readonly ProjectEntry[];
        initialScope?: InstallScope | null;
        initialProject?: string | null;
        runtimeActive?: boolean;
        secrets?: readonly SecretDescriptor[];
        store?: InstallSheetStore;
        loadSheet?: (cplugId: string) => Promise<CplugSheet>;
        onClose: () => void;
        onDone: (result: { id?: string; enabled: boolean; scope?: InstallScope; projectPath?: string | null }) => void;
    }

    const {
        open,
        mode,
        t,
        item = null,
        card = null,
        host = null,
        projects = [],
        initialScope = null,
        initialProject = null,
        runtimeActive,
        secrets: explicitSecrets,
        store = pluginsStore,
        loadSheet = readSheet,
        onClose,
        onDone,
    }: Props = $props();

    let source = $state('');
    let ref = $state('');
    let subdir = $state('');
    let githubPreview = $state<GithubPreviewResponse | null>(null);
    let catalogPreview = $state<InstallPreview | null>(null);
    let enableSheet = $state<CplugSheet | null>(null);
    let loadedProjects = $state<readonly ProjectEntry[]>([]);
    let scope = $state<InstallScope>('global');
    let projectPath = $state<string>('');
    let ticks = $state<Record<string, boolean>>({});
    let slotTicks = $state<Record<string, boolean>>({});
    let secretValues = $state<Record<string, string>>({});
    let flaggedAccepted = $state(false);
    let overrideMode = $state<'enable' | null>(null);
    let overrideItem = $state<CplugItem | null>(null);
    let activateRuntime = $state(true);
    let loadingPreview = $state(false);
    let submitting = $state(false);
    let previewError = $state<string | null>(null);
    let submitError = $state<string | null>(null);

    let activeKey = '';
    let lastPreviewSource = '';
    let lastTypedSource = '';

    function defaultScope(): InstallScope {
        if (mode === 'catalog' && card?.isCplug && !card?.isPlugin) return 'global';
        return initialScope ?? (initialProject ? 'project' : 'global');
    }

    function resetSheetState(): void {
        source = ''; ref = ''; subdir = '';
        githubPreview = null; catalogPreview = null; enableSheet = null;
        overrideMode = null; overrideItem = null;
        scope = defaultScope(); projectPath = initialProject ?? '';
        ticks = {}; slotTicks = {}; secretValues = {}; activateRuntime = true;
        flaggedAccepted = false;
        loadingPreview = false; submitting = false; previewError = null; submitError = null;
        lastPreviewSource = ''; lastTypedSource = '';
    }

    $effect(() => {
        if (!open) { activeKey = ''; return; }
        const key = `${mode}:${item?.cplugId ?? ''}:${card?.id ?? ''}`;
        if (key === activeKey) return;
        activeKey = key;
        resetSheetState();

        if (projects.length === 0 && host?.listProjects) {
            void host.listProjects().then((rows) => {
                loadedProjects = rows.flatMap((r) => (r.path || r.root ? [{ path: (r.path || r.root)!, name: r.name || (r.path || r.root)! }] : []));
            }).catch(() => {});
        }
        if (mode === 'catalog' && card && host) void runCatalogPreview();
        else if (mode === 'enable' && item?.consentRequired) void runEnableSheetLoad(item.cplugId);
    });

    $effect(() => {
        if (!open || mode !== 'github') return;
        const trimmed = source.trim();
        if (trimmed !== lastTypedSource) {
            lastTypedSource = trimmed;
            if (lastPreviewSource && trimmed !== lastPreviewSource) {
                scope = defaultScope();
            }
        }
    });

    const projectChoices = $derived(projects.length > 0 ? projects : loadedProjects);
    const projectSelectOptions = $derived([
        { value: '', label: t('plugins.page.install_sheet.project_placeholder') },
        ...projectChoices.map((p) => ({ value: p.path, label: p.name || p.path })),
    ]);

    const previewExtras = $derived(
        (githubPreview ?? catalogPreview ?? null) as {
            readonly kind?: string;
            readonly supported_scopes?: readonly string[];
            readonly runtime_active?: boolean;
        } | null,
    );

    const effectiveMode = $derived(overrideMode ?? mode);
    const effectiveItem = $derived(overrideItem ?? item);

    const isAgentPlugin = $derived.by(() => {
        if (effectiveMode === 'github') {
            return githubPreview?.kind === 'agent-plugin' || githubPreview?.supported_scopes?.includes('project') === true;
        }
        if (effectiveMode === 'catalog') {
            return card?.isPlugin === true || previewExtras?.kind === 'agent-plugin' || previewExtras?.supported_scopes?.includes('project') === true;
        }
        return effectiveItem?.pluginKind === 'agent-plugin';
    });

    const showScopePicker = $derived(isAgentPlugin && (effectiveMode !== 'github' || githubPreview !== null));

    const effectiveRuntimeActive = $derived.by(() => {
        if (effectiveMode === 'github') return githubPreview?.runtime_active;
        if (effectiveMode === 'catalog') return previewExtras?.runtime_active ?? runtimeActive;
        const itemWithRuntime = effectiveItem as (CplugItem & { readonly runtimeActive?: boolean; readonly detail?: string | null }) | null;
        return (
            runtimeActive ??
            itemWithRuntime?.runtimeActive ??
            (isRuntimeDisabledDetail(effectiveItem?.heldReason) || isRuntimeDisabledDetail(itemWithRuntime?.detail)
                ? false
                : true)
        );
    });

    const showRuntimeToggle = $derived(!isAgentPlugin && effectiveRuntimeActive === false);

    const isUnverified = $derived.by(() => {
        if (effectiveMode === 'github') return Boolean(githubPreview && (githubPreview.unverified || githubPreview.trust_tier === 'unverified_github'));
        if (effectiveMode === 'catalog') return Boolean(card?.untrusted);
        return Boolean(effectiveItem && (effectiveItem.unverified || effectiveItem.trustTier === 'unverified_github'));
    });

    const unverifiedBadge = $derived(
        githubPreview?.trust_badge || effectiveItem?.trustBadge || t('plugins.page.install_sheet.unverified_badge'),
    );

    const facts = $derived(
        deriveSheetFacts({
            mode: effectiveMode,
            githubPreview,
            catalogPreview,
            enableSheet,
            item: effectiveItem,
            explicitSecrets,
            t,
        }),
    );
    const grouped = $derived(groupCapabilities(facts.permissions));
    const pendingSlotTicks = $derived(
        facts.uiSlots.filter((s) => !s.granted && (s.needs_tick || needsTick(s.risk))),
    );
    const hasBlockedSlot = $derived(facts.uiSlots.some((s) => !s.granted && s.risk === 'never'));
    const allTicksChecked = $derived(grouped.pendingTicks.every((p) => ticks[p.name] === true));
    const allSlotTicksChecked = $derived(pendingSlotTicks.every((s) => slotTicks[s.slot] === true));
    const scopeReady = $derived(!showScopePicker || scope === 'global' || Boolean(projectPath));
    const flaggedMeta = $derived(
        effectiveMode === 'catalog'
            ? flaggedMetaFromSheet(catalogPreview, card)
            : flaggedMetaFromSheet(effectiveMode === 'github' ? githubPreview : enableSheet),
    );
    const showFlaggedWarning = $derived(flaggedMeta.flagged || flaggedMeta.requiresWarningAck);
    const hasSubject = $derived(
        (effectiveMode === 'github' && githubPreview !== null) ||
        (effectiveMode === 'catalog' && catalogPreview !== null) ||
        (effectiveMode === 'enable' && effectiveItem !== null),
    );
    const canSubmit = $derived(
        !submitting &&
        !loadingPreview &&
        hasSubject &&
        !card?.revoked &&
        scopeReady &&
        !grouped.hasNever &&
        !hasBlockedSlot &&
        allTicksChecked &&
        allSlotTicksChecked &&
        (!flaggedMeta.requiresWarningAck || flaggedAccepted) &&
        (effectiveMode !== 'enable' || !effectiveItem?.consentRequired || enableSheet !== null),
    );

    const unmetReason = $derived(formatUnmetRequirements(facts.unmetRequirements, t));
    const canEnable = $derived(canSubmit && !unmetReason);

    const hostCount = $derived(facts.networkHosts.length + facts.lanHosts.length);
    const permCount = $derived(facts.permissions.length + facts.uiSlots.length);
    const hasHighOrBlockedPerm = $derived(grouped.hasNever || grouped.high.length > 0 || hasBlockedSlot);

    const sheetTitle = $derived.by(() => {
        if (effectiveMode === 'enable' && effectiveItem) return t('plugins.page.install_sheet.title_enable', { name: effectiveItem.name });
        const named = githubPreview?.name || card?.headline || card?.name || card?.id;
        if (named) return t('plugins.page.install_sheet.title_named', { name: named });
        return t('plugins.page.install_sheet.title_github');
    });

    async function runGithubPreview(req: GithubPreviewRequest): Promise<void> {
        const nextSource = req.source.trim();
        if (lastPreviewSource && nextSource !== lastPreviewSource) {
            scope = defaultScope();
        }
        lastPreviewSource = nextSource;
        loadingPreview = true;
        previewError = null;
        submitError = null;
        ticks = {};
        slotTicks = {};
        secretValues = {};
        activateRuntime = true;
        try {
            githubPreview = await store.previewGithub({
                ...req,
                ...(scope === 'project' && projectPath ? { scope: 'project', project_path: projectPath } : {}),
            });
        } catch (err) {
            if (extractErrorCode(err) === 'scope_unsupported' && scope === 'project') {
                scope = 'global';
                try {
                    githubPreview = await store.previewGithub(req);
                    return;
                } catch (retryErr) {
                    githubPreview = null;
                    previewError = installErrorMessage(retryErr, t);
                    return;
                }
            }
            githubPreview = null;
            previewError = installErrorMessage(err, t);
        } finally {
            loadingPreview = false;
        }
    }

    async function runCatalogPreview(): Promise<void> {
        if (!card || !host) return;
        loadingPreview = true;
        previewError = null;
        submitError = null;
        ticks = {};
        slotTicks = {};
        flaggedAccepted = false;
        if (card.isCplug && !card.isPlugin && scope !== 'global') {
            scope = 'global';
            projectPath = '';
        }
        try {
            const req: InstallRequest = {
                item_id: card.id || '',
                scope,
                ...(scope === 'project' && projectPath ? { project_path: projectPath } : {}),
            };
            catalogPreview = await host.previewInstall(req);
        } catch (err) {
            const errCode = extractErrorCode(err);
            if ((errCode === 'scope_unsupported' || errCode === 'scope_not_supported') && scope === 'project') {
                scope = 'global';
                projectPath = '';
                try {
                    catalogPreview = await host.previewInstall({ item_id: card.id || '', scope: 'global' });
                    return;
                } catch (retryErr) {
                    catalogPreview = null;
                    previewError = installErrorMessage(retryErr, t);
                    return;
                }
            }
            catalogPreview = null;
            previewError = installErrorMessage(err, t);
        } finally {
            loadingPreview = false;
        }
    }

    async function runEnableSheetLoad(cplugId: string): Promise<void> {
        loadingPreview = true;
        previewError = null;
        try {
            enableSheet = await loadSheet(cplugId);
        } catch (err) {
            enableSheet = null;
            previewError = installErrorMessage(err, t);
        } finally {
            loadingPreview = false;
        }
    }

    function itemForSlotConsent(cplugId: string, sheet: CplugSheet): CplugItem {
        const existing = pluginsStore.rowOf(cplugId);
        if (existing) return toCplugItem(existing, t);
        return {
            id: `cplug:${cplugId}`,
            kind: 'cplug',
            cplugId,
            name: card?.headline || card?.name || cplugId,
            brief: null,
            meta: card?.version ?? null,
            marks: [],
            icon: 'plug',
            tags: [],
            byline: card?.publisher ? t('plugins.page.byline', { name: card.publisher }) : null,
            enabled: false,
            version: card?.version ?? '',
            asks: [],
            state: 'disabled',
            blockedBy: [],
            permissions: toPermissionRows(sheet.permissions, t),
            warnings: [],
            consentRequired: true,
            settings: {},
            settingsSchema: null,
            deps: { needs: [], neededBy: [], enabledDependents: [] },
            tier: 'catalog',
            surfaces: {},
            missing: sheet.permissions.filter((p) => !p.granted).map((p) => p.name),
            heldReason: null,
            storageBytes: null,
            thirdParty: true,
            unverified: Boolean(card?.untrusted),
            changedFiles: [],
            publisher: card?.publisher ?? null,
            tools: [],
        };
    }

    async function submit(enable: boolean): Promise<void> {
        if (!canSubmit) return;
        submitting = true;
        submitError = null;
        const selectedTicks = grouped.pendingTicks.filter((p) => ticks[p.name] === true).map((p) => p.name);
        const selectedSlotTicks = pendingSlotTicks.filter((s) => slotTicks[s.slot] === true).map((s) => s.slot);
        try {
            const res = await executeInstallSheetSubmit({
                mode: effectiveMode,
                enable,
                source,
                ref,
                subdir,
                scope,
                projectPath,
                showScopePicker,
                showRuntimeToggle,
                activateRuntime,
                selectedTicks,
                selectedSlotTicks,
                secretValues,
                githubPreview,
                catalogPreview,
                enableSheet,
                item: effectiveItem,
                card,
                host,
                store,
                loadSheet,
                cplugFlaggedAck: flaggedMeta.requiresWarningAck && flaggedAccepted,
            });
            if (res?.needsSlotConsent) {
                enableSheet = res.needsSlotConsent.sheet;
                overrideItem = itemForSlotConsent(res.needsSlotConsent.cplugId, res.needsSlotConsent.sheet);
                overrideMode = 'enable';
                slotTicks = {};
                submitError = t('plugins.page.install_sheet.error.tick_missing');
                return;
            }
            if (res) onDone(res);
        } catch (err) {
            submitError = installErrorMessage(err, t);
        } finally {
            submitting = false;
        }
    }
</script>

{#if open}
    <ModalShell title={sheetTitle} look="titlerow" width="min(560px, 92vw)" dismissable={!submitting} onCancel={onClose} data-install-sheet={effectiveMode}>
        <div class="pl-sheet">
            {#if effectiveMode === 'github'}
                <GithubSourcePicker
                    bind:source
                    bind:ref
                    bind:subdir
                    busy={loadingPreview || submitting}
                    error={previewError}
                    onPreview={runGithubPreview}
                    {t}
                />
            {/if}

            {#if loadingPreview && effectiveMode !== 'github'}
                <p class="pl-sheet__note" data-install-loading>{t('plugins.page.install_sheet.loading_preview')}</p>
            {/if}

            {#if previewError && effectiveMode !== 'github'}
                <p class="pl-sheet__error" role="alert" data-install-error>{previewError}</p>
            {/if}

            {#if hasSubject}
                {#if isUnverified}
                    <div class="pl-sheet__unverified" role="note" data-unverified-banner>
                        <div class="pl-sheet__unverified-head">
                            <Tag tone="danger">{unverifiedBadge}</Tag>
                        </div>
                        <p class="pl-sheet__unverified-copy">{t('plugins.page.install_sheet.unverified_banner')}</p>
                    </div>
                {/if}

                <div class="pl-sheet__meta" data-install-summary>
                    <div class="pl-sheet__ident">
                        {#if githubPreview?.version || card?.version || effectiveItem?.version}
                            <span class="pl-sheet__ident-item">
                                {t('plugins.page.install_sheet.summary_version', {
                                    version: githubPreview?.version || card?.version || effectiveItem?.version || '',
                                })}
                            </span>
                        {/if}
                        {#if card?.publisher || effectiveItem?.publisher}
                            <span class="pl-sheet__ident-item">
                                {t('plugins.page.install_sheet.summary_publisher', {
                                    publisher: card?.publisher || effectiveItem?.publisher || '',
                                })}
                            </span>
                        {/if}
                        {#if githubPreview?.source?.commit}
                            <Tag tone="info">
                                {t('plugins.page.install_sheet.summary_commit', {
                                    commit: githubPreview.source.commit.slice(0, 8),
                                })}
                            </Tag>
                        {/if}
                    </div>
                    {#if !isAgentPlugin}
                        <div class="pl-sheet__status" data-install-quick-status>
                            <Tag tone={permCount === 0 ? 'ok' : hasHighOrBlockedPerm ? 'danger' : 'warn'}>
                                {permCount === 0
                                    ? t('plugins.page.install_sheet.status_no_permissions')
                                    : t('plugins.page.install_sheet.status_permissions_count', { count: permCount })}
                            </Tag>
                            <Tag tone={hostCount === 0 ? 'ok' : 'warn'}>
                                {hostCount === 0
                                    ? t('plugins.page.install_sheet.status_no_network')
                                    : t('plugins.page.install_sheet.status_network_count', { count: hostCount })}
                            </Tag>
                        </div>
                    {/if}
                </div>

                {#if showScopePicker}
                    <fieldset class="pl-sheet__scope" data-install-scope>
                        <legend class="pl-sheet__legend">{t('plugins.page.install_sheet.scope_legend')}</legend>
                        <RadioGroup
                            label={t('plugins.page.install_sheet.scope_legend')}
                            bind:value={scope}
                            disabled={submitting}
                            options={[
                                {
                                    value: 'global',
                                    label: t('plugins.page.install_sheet.scope_global'),
                                    hint: t('plugins.page.install_sheet.scope_global_hint'),
                                },
                                {
                                    value: 'project',
                                    label: t('plugins.page.install_sheet.scope_project'),
                                    hint: t('plugins.page.install_sheet.scope_project_hint'),
                                    disabled: projectChoices.length === 0,
                                },
                            ]}
                        />
                        {#if projectChoices.length === 0}
                            <p class="pl-sheet__note">{t('plugins.page.install_sheet.project_none')}</p>
                        {:else if scope === 'project'}
                            <Select
                                label={t('plugins.page.install_sheet.project_label')}
                                bind:value={projectPath}
                                options={projectSelectOptions}
                                disabled={submitting}
                                data-install-project
                            />
                        {/if}
                    </fieldset>
                {/if}

                {#if showFlaggedWarning}
                    <FlaggedWarningBox
                        summary={flaggedMeta.summary}
                        warningReasons={flaggedMeta.warningReasons}
                        warnings={flaggedMeta.warnings}
                        bind:accepted={flaggedAccepted}
                        busy={submitting}
                        requireAck={flaggedMeta.requiresWarningAck}
                        {t}
                    />
                {/if}

                {#if !isAgentPlugin}
                    <CapabilityCards
                        permissions={facts.permissions}
                        uiSlots={facts.uiSlots}
                        services={facts.services}
                        events={facts.events}
                        warnings={facts.warnings}
                        tools={facts.tools}
                        networkHosts={facts.networkHosts}
                        lanHosts={facts.lanHosts}
                        bind:ticks
                        bind:slotTicks
                        busy={submitting}
                        {t}
                    />

                    <InlineSecretsFields
                        secrets={facts.secrets}
                        bind:values={secretValues}
                        secretsStatus={effectiveItem?.secretsStatus}
                        busy={submitting}
                        {t}
                    />
                {/if}

                {#if showRuntimeToggle}
                    <div class="pl-sheet__runtime" data-runtime-toggle>
                        <Checkbox
                            label={t('plugins.page.install_sheet.runtime_label')}
                            hint={t('plugins.page.install_sheet.runtime_hint')}
                            bind:checked={activateRuntime}
                            disabled={submitting}
                            data-runtime-checkbox
                        />
                    </div>
                {/if}
            {/if}

            {#if unmetReason}
                <p class="pl-sheet__error" role="alert" data-install-unmet>{unmetReason}</p>
            {/if}

            {#if submitError}
                <p class="pl-sheet__error" role="alert" data-install-error>{submitError}</p>
            {/if}
        </div>

        {#snippet footer()}
            <div class="pl-sheet__footer">
                <span class="pl-sheet__footer-left">
                    <Button variant="quiet" disabled={submitting} data-install-cancel onclick={onClose}>
                        {t('plugins.page.install_sheet.cta_cancel')}
                    </Button>
                </span>
                <div class="pl-sheet__footer-acts">
                    {#if effectiveMode !== 'enable'}
                        <Button variant="secondary" disabled={!canSubmit} data-install-disabled onclick={() => void submit(false)}>
                            {t('plugins.page.install_sheet.cta_install_disabled')}
                        </Button>
                    {/if}
                    <Button variant="confirm" disabled={!canEnable} data-install-enable onclick={() => void submit(true)}>
                        {t(submitting ? 'plugins.page.install_sheet.cta_installing' : 'plugins.page.install_sheet.cta_install_enable')}
                    </Button>
                </div>
            </div>
        {/snippet}
    </ModalShell>
{/if}

<style>
    @layer components {
        .pl-sheet {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            font-size: var(--oc-fs-body);
            line-height: var(--oc-lh-body);
        }

        .pl-sheet__unverified {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1);
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-coral);
            border-radius: var(--oc-radius-panel);
            background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-field));
        }

        .pl-sheet__unverified-head {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
        }

        .pl-sheet__unverified-copy {
            margin: 0;
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-label);
        }

        .pl-sheet__meta {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
        }

        .pl-sheet__ident {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1-5);
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }

        .pl-sheet__ident-item + .pl-sheet__ident-item::before {
            content: '\00b7';
            margin-right: var(--oc-space-1-5);
            color: var(--oc-text-muted);
        }

        .pl-sheet__status {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1-5);
        }

        .pl-sheet__footer {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: flex-end;
            gap: var(--oc-space-2);
            width: 100%;
        }

        .pl-sheet__footer-left {
            margin-right: auto;
        }

        .pl-sheet__footer-acts {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: flex-end;
            gap: var(--oc-space-2);
        }

        .pl-sheet__scope {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            margin: 0;
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-line-surface);
            border-radius: var(--oc-radius-panel);
        }

        .pl-sheet__legend {
            padding: 0 var(--oc-space-1);
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .pl-sheet__runtime {
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-line-surface);
            border-radius: var(--oc-radius-panel);
            background: var(--oc-surface-raised);
        }

        .pl-sheet__note {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }

        .pl-sheet__error {
            margin: 0;
            padding: var(--oc-space-1-5) var(--oc-space-2);
            border-left: var(--oc-border) solid var(--oc-coral);
            background: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-field));
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
            overflow-wrap: anywhere;
        }
    }
</style>

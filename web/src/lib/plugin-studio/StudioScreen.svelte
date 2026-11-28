<script lang="ts">
    import { onDestroy, onMount, untrack } from 'svelte';
    import Page from '../../opscenter/ui/Page.svelte';
    import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import { openSettings, openWrappers } from '../../opscenter/api/host';
    import { Button, Field, IconButton, List, ListRow, Segmented, Select, State, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import MultiThemePreview from './MultiThemePreview.svelte';
    import ReadinessChecklist from './ReadinessChecklist.svelte';
    import { closePluginStudio } from './screen-host';
    import StudioActionsBar from './StudioActionsBar.svelte';
    import StudioInspectorPane from './StudioInspectorPane.svelte';
    import StudioTerminalPane from './StudioTerminalPane.svelte';
    import { studioStore } from './studio-store.svelte';
    import type { StudioAgentKind, StudioOpenOptions, StudioTemplate } from './types';
    import './plugin-studio.css';

    interface Props {
        embedded?: boolean;
        initialOptions?: StudioOpenOptions;
        onClose?: () => void;
        t?: Translate;
    }

    type RightTabId = 'preview' | 'inspector' | 'readiness';

    const TEMPLATE_KEYS: Array<{ value: StudioTemplate; labelKey: string }> = [
        { value: 'no-code', labelKey: 'plugin_studio.template.no_code' },
        { value: 'python', labelKey: 'plugin_studio.template.python' },
        { value: 'typescript', labelKey: 'plugin_studio.template.typescript' },
        { value: 'bash', labelKey: 'plugin_studio.template.bash' },
        { value: 'widget', labelKey: 'plugin_studio.template.widget' },
        { value: 'channel', labelKey: 'plugin_studio.template.channel' },
        { value: 'agent-harness', labelKey: 'plugin_studio.template.agent_harness' },
    ];

    const AGENT_KEYS: Array<{ value: StudioAgentKind; labelKey: string }> = [
        { value: 'claude', labelKey: 'plugin_studio.agent.claude' },
        { value: 'codex', labelKey: 'plugin_studio.agent.codex' },
        { value: 'agy', labelKey: 'plugin_studio.agent.agy' },
    ];

    const { embedded = false, initialOptions, onClose, t = appT }: Props = $props();

    let prompt = $state(untrack(() => initialOptions?.initialPrompt ?? ''));
    let name = $state(untrack(() => initialOptions?.initialName ?? ''));
    let template = $state<StudioTemplate>(untrack(() => initialOptions?.template ?? 'python'));
    let agentKind = $state<StudioAgentKind>(untrack(() => initialOptions?.agentKind ?? 'claude'));
    let activeTab = $state<RightTabId>('preview');

    const tabs = $derived<TabDef[]>([
        { id: 'preview', label: t('plugin_studio.tab.preview') },
        { id: 'inspector', label: t('plugin_studio.tab.inspector') },
        {
            id: 'readiness',
            label: t('plugin_studio.tab.readiness'),
            badge: studioStore.readiness?.summary.fail ? studioStore.readiness.summary.fail : null,
        },
    ]);

    const templateOptions = $derived(
        TEMPLATE_KEYS.map((item) => ({ value: item.value, label: t(item.labelKey) })),
    );

    const agentOptions = $derived(
        AGENT_KEYS.map((item) => ({ value: item.value, label: t(item.labelKey) })),
    );

    const themeChoices = $derived(studioStore.themeOptions());
    const detail = $derived(studioStore.detail);
    const activeWorkspace = $derived(detail?.workspace ?? null);

    const actionableErrorTitle = $derived.by(() => {
        const err = studioStore.error;
        if (!err) return '';
        if (err.code === 'developer_mode_off') return t('plugin_studio.error.developer_mode_off');
        if (err.code === 'agy_profile_not_configured') return t('plugin_studio.error.agy_profile_not_configured');
        if (err.code === 'folder_refused') return t('plugin_studio.error.folder_refused');
        return err.message;
    });

    async function handleCreateSubmit(): Promise<void> {
        const cleanPrompt = prompt.trim();
        if (!cleanPrompt) return;
        const created = await studioStore.createAndLaunch({
            prompt: cleanPrompt,
            name: name.trim() || null,
            template,
            agent_kind: agentKind,
            start_agent: true,
            start_dev: true,
        });
        if (created) {
            prompt = '';
            name = '';
        }
    }

    function handleTabSelect(nextId: string): void {
        if (nextId === 'preview' || nextId === 'inspector' || nextId === 'readiness') {
            activeTab = nextId;
            if (nextId === 'readiness' && studioStore.activeId && !studioStore.readiness) {
                void studioStore.loadReadiness(false);
            }
        }
    }

    function handleErrorAction(code: string): void {
        if (onClose) {
            onClose();
        } else {
            closePluginStudio();
        }
        if (code === 'agy_profile_not_configured') {
            openWrappers();
        } else {
            openSettings();
        }
    }

    onMount(() => {
        void studioStore.refreshWorkspaces(initialOptions?.studioId ?? null);
    });

    onDestroy(() => {
        studioStore.dispose();
    });
</script>

<Page
    title={t('plugin_studio.title')}
    frame="nav"
    scroll="self"
    {embedded}
    {onClose}
    sideLabel={activeWorkspace?.name ?? t('plugin_studio.workspaces.heading')}
>
    {#snippet side()}
        <div class="ps-rail" data-studio-rail>
            <div class="ps-rail__section">
                <div class="ps-rail__headrow">
                    <h3 class="ps-rail__heading">{t('plugin_studio.workspaces.heading')}</h3>
                    <span class="ps-rail__count">
                        {t('plugin_studio.workspaces.count', { count: studioStore.workspaces.length })}
                    </span>
                </div>

                {#if studioStore.workspaces.length === 0}
                    <State kind="empty" title={t('plugin_studio.workspaces.empty')} />
                {:else}
                    <List label={t('plugin_studio.workspaces.heading')}>
                        {#each studioStore.workspaces as ws (ws.studio_id)}
                            {@const active = ws.studio_id === studioStore.activeId}
                            <ListRow
                                primary={ws.name || ws.plugin_id}
                                secondary={`${ws.template} · ${ws.agent_kind}`}
                                selected={active}
                                onclick={() => void studioStore.selectWorkspace(ws.studio_id)}
                                data-studio-workspace={ws.studio_id}
                            >
                                {#snippet actions()}
                                    <div class="ps-workspace-item__meta">
                                        {#if ws.dev_active}
                                            <Tag tone="ok">{t('plugin_studio.workspaces.dev_badge')}</Tag>
                                        {/if}
                                        <IconButton
                                            icon="trash"
                                            label={t('plugin_studio.workspaces.delete', { name: ws.name || ws.plugin_id })}
                                            onclick={(e) => {
                                                e.stopPropagation();
                                                void studioStore.removeWorkspace(ws.studio_id, true);
                                            }}
                                            data-studio-delete={ws.studio_id}
                                        />
                                    </div>
                                {/snippet}
                            </ListRow>
                        {/each}
                    </List>
                {/if}
            </div>

            <form
                class="ps-form"
                data-studio-create-form
                onsubmit={(e) => {
                    e.preventDefault();
                    void handleCreateSubmit();
                }}
            >
                <h3 class="ps-rail__heading">{t('plugin_studio.form.heading')}</h3>

                <Field
                    label={t('plugin_studio.form.prompt')}
                    placeholder={t('plugin_studio.form.prompt_placeholder')}
                    multiline={true}
                    rows={3}
                    bind:value={prompt}
                    data-studio-prompt
                />

                <Field
                    label={t('plugin_studio.form.name')}
                    placeholder={t('plugin_studio.form.name_placeholder')}
                    bind:value={name}
                    data-studio-name
                />

                <Select
                    label={t('plugin_studio.form.template')}
                    bind:value={template}
                    options={templateOptions}
                    data-studio-template
                />

                <div class="ps-rail__section">
                    <span class="ps-form__label">{t('plugin_studio.form.agent')}</span>
                    <Segmented
                        label={t('plugin_studio.form.agent')}
                        value={agentKind}
                        options={agentOptions}
                        onchange={(val) => {
                            if (val === 'claude' || val === 'codex' || val === 'agy') agentKind = val;
                        }}
                    />
                </div>

                <Button
                    type="submit"
                    variant="confirm"
                    disabled={studioStore.busyAction !== null || !prompt.trim()}
                    data-studio-create-submit
                >
                    {studioStore.busyAction === 'create'
                        ? t('plugin_studio.form.creating')
                        : t('plugin_studio.form.create_launch')}
                </Button>
            </form>
        </div>
    {/snippet}

    <div class="ps-shell" data-studio-shell>
        {#if studioStore.error}
            <div class="ps-banner" role="alert" data-studio-error={studioStore.error.code}>
                <div class="ps-banner__head">
                    <p class="ps-banner__title">{actionableErrorTitle}</p>
                    <IconButton
                        icon="close"
                        label={t('plugin_studio.close')}
                        onclick={() => studioStore.clearError()}
                    />
                </div>
                {#if studioStore.error.message !== actionableErrorTitle}
                    <p class="ps-banner__detail">{studioStore.error.message}</p>
                {/if}
                {#if studioStore.error.refusals.length > 0}
                    <ul class="ps-findings">
                        {#each studioStore.error.refusals as refusal, idx (`refusal-${idx}`)}
                            <li>{refusal.reason ?? refusal.detail ?? JSON.stringify(refusal)}</li>
                        {/each}
                    </ul>
                {/if}
                {#if studioStore.error.code === 'developer_mode_off' || studioStore.error.code === 'agy_profile_not_configured'}
                    {@const errCode = studioStore.error.code}
                    <div class="ps-banner__actions">
                        <Button variant="secondary" data-studio-error-action onclick={() => handleErrorAction(errCode)}>
                            {errCode === 'agy_profile_not_configured'
                                ? t('plugin_studio.error.open_profiles')
                                : t('plugin_studio.error.open_settings')}
                        </Button>
                    </div>
                {/if}
            </div>
        {/if}

        {#if studioStore.loading && !detail}
            <State kind="loading" title={t('plugin_studio.loading')} />
        {:else if !detail || !activeWorkspace}
            <State
                kind="empty"
                title={t('plugin_studio.empty.title')}
                hint={t('plugin_studio.empty.hint')}
            />
        {:else}
            <div class="ps-workbench">
                <StudioTerminalPane
                    workspace={activeWorkspace}
                    files={detail.files}
                    sessionStatus={detail.session_status}
                    devStatus={detail.dev_status}
                    busy={studioStore.busyAction !== null}
                    onStartDev={() => studioStore.startDevMode(true)}
                    onStopDev={() => studioStore.stopDevMode()}
                    onRelaunchAgent={() => studioStore.relaunchAgent({ agent_kind: activeWorkspace.agent_kind })}
                    {t}
                />

                <div class="ps-pane">
                    <Tabs
                        {tabs}
                        active={activeTab}
                        onSelect={handleTabSelect}
                        label={t('plugin_studio.tabs.label')}
                        idBase="plugin-studio"
                    />

                    {#if activeTab === 'preview'}
                        <div {...panelAttrs('plugin-studio', 'preview')}>
                            <MultiThemePreview
                                workspace={activeWorkspace}
                                capabilities={detail.inspector?.capabilities ?? null}
                                previewByTheme={studioStore.previewByTheme}
                                fallbackPreview={detail.preview}
                                selectedThemes={studioStore.selectedThemes}
                                {themeChoices}
                                surfaceId={studioStore.surfaceId}
                                viewportWidth={studioStore.viewportWidth}
                                viewportHeight={studioStore.viewportHeight}
                                loading={studioStore.busyAction === 'preview'}
                                onToggleTheme={(id) => studioStore.toggleTheme(id)}
                                onSelectSurface={(id) => studioStore.setSurface(id)}
                                onSelectViewport={(w, h) => studioStore.setViewport(w, h)}
                                onRefresh={() => studioStore.refreshPreviews(activeWorkspace.studio_id)}
                                {t}
                            />
                        </div>
                    {:else if activeTab === 'inspector'}
                        <div {...panelAttrs('plugin-studio', 'inspector')}>
                            <StudioInspectorPane
                                pluginId={activeWorkspace.plugin_id}
                                studioInspector={detail.inspector}
                                liveInspector={studioStore.pluginInspector}
                                devEvents={studioStore.devEvents}
                                loading={studioStore.busyAction === 'detail'}
                                {t}
                            />
                        </div>
                    {:else}
                        <div {...panelAttrs('plugin-studio', 'readiness')}>
                            <ReadinessChecklist
                                readiness={studioStore.readiness}
                                busy={studioStore.busyAction === 'readiness'}
                                onRecheck={(runTests) => studioStore.loadReadiness(runTests)}
                                {t}
                            />
                        </div>
                    {/if}
                </div>
            </div>

            <StudioActionsBar
                busyAction={studioStore.busyAction}
                sandboxResult={studioStore.sandboxResult}
                installResult={studioStore.installResult}
                publishPreview={studioStore.publishPreview}
                publishResult={studioStore.publishResult}
                onTestSandbox={() => studioStore.runSandboxTests()}
                onInstall={() => studioStore.installActive()}
                onPublish={(req) => studioStore.publishActive(req)}
                onResetPublish={() => studioStore.resetPublishState()}
                {t}
            />
        {/if}
    </div>
</Page>

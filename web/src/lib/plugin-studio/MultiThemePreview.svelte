<script lang="ts">
    import { Button, Checkbox, Segmented, Select, State, Tag } from '../base';
    import Renderer from '../cplug-ui/Renderer.svelte';
    import ViewFrame from '../cplug-ui/ViewFrame.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { ThemeChoice } from '../../plugins/sdk/themes';
    import { resolveThemePreview } from './theme-bridge';
    import type { PreviewRenderResponse, StudioDeclaredCapabilities, StudioWorkspace } from './types';
    import './plugin-studio.css';

    interface Props {
        workspace: StudioWorkspace;
        capabilities: StudioDeclaredCapabilities | null;
        previewByTheme: Record<string, PreviewRenderResponse>;
        fallbackPreview: PreviewRenderResponse | null;
        selectedThemes: string[];
        themeChoices: ThemeChoice[];
        surfaceId: string | null;
        viewportWidth: number;
        viewportHeight?: number;
        loading?: boolean;
        onToggleTheme: (themeId: string) => void;
        onSelectSurface: (surfaceId: string | null) => void;
        onSelectViewport: (width: number, height: number) => void;
        onRefresh: () => Promise<unknown>;
        t?: Translate;
    }

    const {
        workspace,
        capabilities,
        previewByTheme,
        fallbackPreview,
        selectedThemes,
        themeChoices,
        surfaceId,
        viewportWidth,
        viewportHeight = 320,
        loading = false,
        onToggleTheme,
        onSelectSurface,
        onSelectViewport,
        onRefresh,
        t = appT,
    }: Props = $props();

    const VIEWPORTS = [
        { key: '320', width: 320, height: 240, labelKey: 'plugin_studio.preview.viewport_s' },
        { key: '480', width: 480, height: 320, labelKey: 'plugin_studio.preview.viewport_m' },
        { key: '720', width: 720, height: 480, labelKey: 'plugin_studio.preview.viewport_l' },
    ] as const;

    const surfaceOptions = $derived.by(() => {
        const names = [
            ...(capabilities?.views ?? []),
            ...(capabilities?.ui_slots ?? []),
        ].filter((v, idx, arr) => Boolean(v) && arr.indexOf(v) === idx);
        return names.map((name) => ({ value: name, label: name }));
    });

    const viewportKey = $derived(
        VIEWPORTS.find((vp) => vp.width === viewportWidth)?.key ?? '480',
    );

    const declaredForRenderer = $derived({
        routes: capabilities?.routes ?? [],
        tools: capabilities?.tools ?? [],
    });

    const pluginStub = $derived({
        cplugId: workspace.plugin_id,
        name: workspace.name || workspace.plugin_id,
        unverified: true,
        declared: declaredForRenderer,
        installKey: workspace.studio_id,
    });

    function handleViewportChange(nextKey: string): void {
        const hit = VIEWPORTS.find((vp) => vp.key === nextKey);
        if (hit) onSelectViewport(hit.width, hit.height);
    }
</script>

<div class="ps-right-body" data-studio-preview>
    <div class="ps-preview-controls">
        <div class="ps-theme-picker" aria-label={t('plugin_studio.preview.themes_label')}>
            <span class="ps-form__label">{t('plugin_studio.preview.themes_label')}</span>
            {#each themeChoices as choice (choice.id)}
                <Checkbox
                    label={choice.name}
                    checked={selectedThemes.includes(choice.id)}
                    data-studio-theme-choice={choice.id}
                    onchange={() => onToggleTheme(choice.id)}
                />
            {/each}
        </div>

        <div class="ps-pane__controls">
            {#if surfaceOptions.length > 0}
                <Select
                    size="sm"
                    aria-label={t('plugin_studio.preview.surface_label')}
                    value={surfaceId ?? surfaceOptions[0]?.value ?? ''}
                    options={surfaceOptions}
                    onchange={(e) => onSelectSurface((e.currentTarget as HTMLSelectElement).value || null)}
                />
            {/if}
            <Segmented
                label={t('plugin_studio.preview.viewport_label')}
                value={viewportKey}
                options={VIEWPORTS.map((vp) => ({ value: vp.key, label: t(vp.labelKey) }))}
                onchange={handleViewportChange}
            />
            <Button
                variant="secondary"
                disabled={loading}
                data-studio-refresh-preview
                onclick={() => void onRefresh()}
            >
                {loading ? t('plugin_studio.preview.refreshing') : t('plugin_studio.preview.refresh')}
            </Button>
        </div>
    </div>

    {#if selectedThemes.length === 0}
        <State kind="empty" title={t('plugin_studio.preview.need_two')} />
    {:else}
        <div class="ps-theme-grid" data-studio-theme-grid>
            {#each selectedThemes as themeId (themeId)}
                {@const resolved = resolveThemePreview(themeId, themeChoices)}
                {@const preview = previewByTheme[themeId] ?? fallbackPreview}
                <section class="ps-stage" data-studio-preview-stage={themeId}>
                    <header class="ps-stage__head">
                        <span class="ps-stage__name">{resolved.name}</span>
                        {#if preview?.kind === 'declarative'}
                            <Tag tone="info">{t('plugin_studio.preview.declarative_badge')}</Tag>
                        {:else if preview?.kind === 'view'}
                            <Tag tone="info">{t('plugin_studio.preview.iframe_badge')}</Tag>
                        {/if}
                    </header>

                    {#if !preview || preview.kind === 'none'}
                        <div
                            class="ps-stage__canvas"
                            style:--ps-stage-w={`${viewportWidth}px`}
                            style:--ps-stage-h={`${viewportHeight}px`}
                        >
                            <State
                                kind="empty"
                                title={t('plugin_studio.preview.empty')}
                                hint={t('plugin_studio.preview.empty_hint')}
                            />
                        </div>
                    {:else if preview.kind === 'error' || preview.errors?.length}
                        <div
                            class="ps-stage__canvas"
                            style:--ps-stage-w={`${viewportWidth}px`}
                            style:--ps-stage-h={`${viewportHeight}px`}
                        >
                            <ul class="ps-findings" data-studio-preview-errors>
                                {#each preview.errors as err, idx (`${err.code}-${idx}`)}
                                    <li>
                                        {err.code}{err.path ? ` (${err.path})` : ''}{err.detail ? `: ${err.detail}` : ''}
                                    </li>
                                {/each}
                            </ul>
                        </div>
                    {:else if preview.kind === 'declarative' && preview.doc}
                        <div
                            class="ps-stage__canvas"
                            data-session-theme={themeId}
                            style={resolved.ocStyle}
                            style:--ps-stage-w={`${viewportWidth}px`}
                            style:--ps-stage-h={`${viewportHeight}px`}
                        >
                            <Renderer
                                cplugId={workspace.plugin_id}
                                name={workspace.name || workspace.plugin_id}
                                unverified={true}
                                document={preview.doc}
                                declared={declaredForRenderer}
                                bar={false}
                                {t}
                            />
                        </div>
                    {:else if preview.kind === 'view' && preview.view_url}
                        <div
                            class="ps-stage__frame"
                            data-studio-preview-view={themeId}
                            style:--ps-stage-w={`${viewportWidth}px`}
                            style:--ps-stage-h={`${viewportHeight}px`}
                        >
                            <ViewFrame
                                plugin={pluginStub}
                                view={preview.surface ?? 'studio'}
                                surface="panel"
                                bar={false}
                                fill={true}
                                themeValues={resolved.themeValues}
                                viewSrc={preview.view_url}
                                {t}
                            />
                        </div>
                    {:else}
                        <div
                            class="ps-stage__canvas"
                            style:--ps-stage-w={`${viewportWidth}px`}
                            style:--ps-stage-h={`${viewportHeight}px`}
                        >
                            <State
                                kind="empty"
                                title={t('plugin_studio.preview.empty')}
                                hint={t('plugin_studio.preview.empty_hint')}
                            />
                        </div>
                    {/if}
                </section>
            {/each}
        </div>
    {/if}
</div>

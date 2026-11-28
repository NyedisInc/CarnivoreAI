
<script lang="ts">
    import Segmented from '../base/Segmented.svelte';
    import { t } from '../i18n/index.svelte';
    import type { Surface } from './api';
    import CplugSurface from './CplugSurface.svelte';
    import { pluginTabOf } from './plugin-tabs.svelte';
    import ViewFrame from './ViewFrame.svelte';

    let { tabId, popout = false }: { tabId?: string; popout?: boolean } = $props();

    const entry = $derived(tabId ? pluginTabOf(tabId) : undefined);
    let pageStep = $state<'main' | 'menu'>('main');
    const pageOptions = $derived([
        { value: 'main', label: t('cplug_ui.page.step_view'), attrs: { 'data-page-step-key': 'view' } },
        { value: 'menu', label: t('cplug_ui.page.step_menu'), attrs: { 'data-page-step-key': 'menu' } },
    ]);
</script>

<div class="cu-page" data-plugin-tab-body={entry?.tabId}>
    {#if entry}
        {#key entry.key}
            {#if entry.kind === 'sidebar_tab'}
                {#if entry.view}
                    <ViewFrame plugin={entry.plugin} view={entry.view} surface="panel" bar={!popout} fill viewRole="menu" {t} />
                {:else}
                    <CplugSurface plugin={entry.plugin} surface={(entry.surface ?? 'tab') as Surface} bar={!popout} fill {t} />
                {/if}
            {:else if entry.main}
                {#if entry.menu && entry.menu !== entry.main}
                    <Segmented label={t('cplug_ui.page.steps')} bind:value={pageStep} options={pageOptions} data-page-switch />
                    <div class="cu-page__step" data-page-step="view" hidden={pageStep !== 'main'}>
                        <ViewFrame plugin={entry.plugin} view={entry.main} surface="panel" bar={!popout} fill viewRole="page" visible={pageStep === 'main'} {t} />
                    </div>
                    <div class="cu-page__step" data-page-step="menu" hidden={pageStep !== 'menu'}>
                        <ViewFrame plugin={entry.plugin} view={entry.menu} surface="panel" bar={!popout} fill viewRole="menu" visible={pageStep === 'menu'} {t} />
                    </div>
                {:else}
                    <ViewFrame plugin={entry.plugin} view={entry.main} surface="panel" bar={!popout} fill viewRole="page" {t} />
                {/if}
            {/if}
        {/key}
    {:else}
        <p class="cu-page__off" role="status">{t('cplug_ui.panel_off')}</p>
    {/if}
</div>

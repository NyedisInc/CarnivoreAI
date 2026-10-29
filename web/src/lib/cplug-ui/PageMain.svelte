<!-- the main area is as it was -->
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { pageOf } from './page-views.svelte';
    import ViewFrame from './ViewFrame.svelte';

    let { tabId }: { tabId?: string } = $props();

    const entry = $derived(tabId ? pageOf(tabId) : undefined);
</script>

<div class="cu-page cu-page--main" data-page-main>
    {#if entry}
        {#key entry.key}
            <ViewFrame plugin={entry.plugin} view={entry.main} surface="panel" viewRole="page" {t} />
        {/key}
    {:else}
        <p class="cu-page__off" role="status">{t('cplug_ui.panel_off')}</p>
    {/if}
</div>

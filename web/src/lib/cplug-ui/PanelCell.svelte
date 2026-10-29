
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import ViewFrame from './ViewFrame.svelte';
    import { panelOf } from './panel-views.svelte';

    let { instance }: { instance?: string } = $props();

    const entry = $derived.by(() => {
        const [kind = '', tail = ''] = (instance ?? '').split(':');
        const live = panelOf(kind);
        return live && live.tail === tail ? live : undefined;
    });
</script>

<div class="cu-panelcell" data-panel-cell>
    {#if entry}
        {#key entry.key}
            <ViewFrame plugin={entry.plugin} view={entry.view} surface="panel" {t} />
        {/key}
    {:else}
        <p class="cu-panelcell__off" role="status">{t('cplug_ui.panel_off')}</p>
    {/if}
</div>

<style>
    .cu-panelcell {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 0;
        min-width: 0;
    }
    .cu-panelcell > :global(.cu-frame) {
        flex: 1;
        min-height: 0;
    }
    .cu-panelcell :global(.cu-box) {
        flex: 1;
        min-height: 0;
        max-height: none;
        overflow: hidden;
    }
    .cu-panelcell :global(.cu-gate),
    .cu-panelcell :global(.cu-view) {
        height: 100%;
    }
    .cu-panelcell__off {
        margin: 0;
        padding: var(--oc-space-3);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-body);
        color: var(--oc-text-dim, inherit);
    }
</style>

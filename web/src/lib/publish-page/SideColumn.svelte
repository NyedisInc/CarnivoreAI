
<script lang="ts">
    import CardPanel from './CardPanel.svelte';
    import { selectedRecord } from './item-model';
    import type { PageProps } from './props';
    import Timeline from './Timeline.svelte';
    import './side.css';

    const { store, actions, t }: PageProps = $props();
    const rec = $derived(selectedRecord(store));
</script>

{#if rec}
    <div class="d-card" data-pp="SideColumn"><CardPanel {store} {actions} {t} {rec} /></div>
    <div class="d-logwrap"><Timeline {store} {actions} {t} {rec} /></div>
{/if}

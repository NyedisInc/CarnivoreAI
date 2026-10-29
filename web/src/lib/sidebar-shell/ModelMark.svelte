
<script lang="ts">
    import type { ModelPlan } from './row-plan';
    import RowChip from './RowChip.svelte';

    let { model }: { model: ModelPlan } = $props();
</script>

{#snippet mark()}<RowChip chip={{ attrs: model.attrs }}><svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden="true">{@html model.svg}</svg>{#if model.sheen}<span class="effort-fx" data-anim-host aria-hidden="true"><i></i><i></i><i></i></span>{/if}</RowChip>{/snippet}
{#if model.spark}<span class="session-sidebar-row-model-wrap">{@render mark()}<span class="session-sidebar-row-model__spark" aria-hidden="true"></span></span>{:else}{@render mark()}{/if}

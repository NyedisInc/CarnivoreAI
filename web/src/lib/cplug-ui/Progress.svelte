
<script lang="ts">
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'progress' }> } = $props();
    const ctx = useRender();
    const maxRaw = $derived(node.max !== undefined ? Number(resolve(node.max, ctx.data)) : 100);
    const max = $derived(Number.isFinite(maxRaw) && maxRaw > 0 ? maxRaw : 100);
    const valRaw = $derived(node.value !== undefined ? Number(resolve(node.value, ctx.data)) : 0);
    const value = $derived(Number.isFinite(valRaw) ? Math.min(max, Math.max(0, valRaw)) : 0);
    const pct = $derived(Math.round((value / max) * 100));
</script>

<div class="cu-progress" data-cu="progress" data-tone={node.tone ?? 'normal'} data-indeterminate={node.indeterminate ? '' : undefined}>
    <div class="cu-progress__head">
        <span class="cu-progress__label">{node.label}</span>
        {#if !node.indeterminate}<span class="cu-progress__pct">{pct}%</span>{/if}
    </div>
    <div
        class="cu-progress__track"
        role="progressbar"
        aria-label={node.label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={node.indeterminate ? undefined : value}
    >
        {#if node.indeterminate}
            <div class="cu-progress__fill cu-progress__fill--indeterminate"></div>
        {:else}
            <div class="cu-progress__fill" style:width={`${pct}%`}></div>
        {/if}
    </div>
</div>

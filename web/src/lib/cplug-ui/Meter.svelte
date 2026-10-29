
<script lang="ts">
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'meter' }> } = $props();
    const ctx = useRender();
    const value = $derived(Number(resolve(node.value, ctx.data)));
    const max = $derived(Number(resolve(node.max, ctx.data)));
    const fraction = $derived(Number.isFinite(value) && Number.isFinite(max) && max > 0 ? Math.min(1, Math.max(0, value / max)) : 0);
    const level = $derived((node.thresholds ?? []).filter((limit) => value >= limit).length);
</script>

<div class="cu-meter" data-cu="meter" data-level={Math.min(level, 2)}>
    <span class="cu-meter__label">{node.label}</span>
    <div class="cu-meter__track" role="meter" aria-label={node.label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}><div class="cu-meter__fill" style:width={`${Math.round(fraction * 100)}%`}></div></div>
</div>

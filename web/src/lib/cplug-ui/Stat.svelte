
<script lang="ts">
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'stat' }> } = $props();
    const ctx = useRender();
</script>

<div class="cu-stat" data-cu="stat" data-tone={node.tone ?? 'normal'}>
    <span class="cu-stat__label">{node.label}</span>
    <span class="cu-stat__value">{resolve(node.value, ctx.data)}{#if node.unit}<span class="cu-stat__unit"> {node.unit}</span>{/if}</span>
    {#if node.delta}<span class="cu-stat__delta">{node.delta}</span>{/if}
</div>


<script lang="ts">
    import Node from './Node.svelte';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'row' | 'column' }> } = $props();
</script>

<div class="cu-layout" data-cu={node.type} data-gap={node.gap ?? 2} data-wrap={node.wrap ? '' : undefined}>
    {#each node.children as child}<Node node={child} />{/each}
</div>

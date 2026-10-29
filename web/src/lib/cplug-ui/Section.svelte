
<script lang="ts">
    import Node from './Node.svelte';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'section' }> } = $props();
</script>

<section class="cu-section" data-cu="section">
    {#if node.title}<h3 class="pl-label cu-section__title">{node.title}</h3>{/if}
    {#each node.children as child}<Node node={child} />{/each}
</section>

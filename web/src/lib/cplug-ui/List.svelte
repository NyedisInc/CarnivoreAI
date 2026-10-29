
<script lang="ts">
    import Node from './Node.svelte';
    import { useRender } from './context';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'list' }> } = $props();
    const { t } = useRender();
</script>

<ul class="cu-list" data-cu="list">
    {#each node.items as item}<li class="cu-list__item"><Node node={item} /></li>{:else}<li class="cu-list__empty">{node.empty ?? t('cplug_ui.list_empty')}</li>{/each}
</ul>

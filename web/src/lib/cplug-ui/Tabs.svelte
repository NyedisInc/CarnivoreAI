
<script lang="ts">
    import { untrack } from 'svelte';
    import BaseTabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import { useRender } from './context';
    import Node from './Node.svelte';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'tabs' }> } = $props();
    const ctx = useRender();
    const uid = $props.id();
    const idBase = `cu-tabs-${uid}`;

    function pickDefault(): string {
        if (node.active && node.items.some((item) => item.id === node.active)) return node.active;
        return node.items[0]?.id ?? '';
    }

    let activeId = $state(untrack(() => pickDefault()));
    let lastInitial = untrack(() => node.active);

    $effect(() => {
        if (node.active !== lastInitial) {
            lastInitial = node.active;
            activeId = pickDefault();
        } else if (!node.items.some((item) => item.id === activeId)) {
            activeId = pickDefault();
        }
    });

    const tabs = $derived<TabDef[]>(node.items.map((item) => ({ id: item.id, label: item.label })));
</script>

<div class="cu-tabset" data-cu="tabs">
    <BaseTabs {tabs} active={activeId} onSelect={(id) => (activeId = id)} label={ctx.t('cplug_ui.tabs_label')} {idBase} />
    {#each node.items as item (item.id)}
        <div class="cu-tabpanel" {...panelAttrs(idBase, item.id)} hidden={item.id !== activeId}>
            {#if item.content}<Node node={item.content} />{/if}
            {#if item.children}{#each item.children as child}<Node node={child} />{/each}{/if}
        </div>
    {/each}
</div>

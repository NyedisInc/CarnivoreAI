
<script lang="ts">
    import type { UiNode } from './validate';
    import Badge from './Badge.svelte';
    import Button from './Button.svelte';
    import Layout from './Layout.svelte';
    import List from './List.svelte';
    import Meter from './Meter.svelte';
    import Section from './Section.svelte';
    import Stat from './Stat.svelte';
    import Table from './Table.svelte';
    import Text from './Text.svelte';

    const { node }: { node: UiNode } = $props();
</script>

{#if node.type === 'section'}<Section {node} />
{:else if node.type === 'row' || node.type === 'column'}<Layout {node} />
{:else if node.type === 'text'}<Text {node} />
{:else if node.type === 'badge'}<Badge {node} />
{:else if node.type === 'stat'}<Stat {node} />
{:else if node.type === 'list'}<List {node} />
{:else if node.type === 'table'}<Table {node} />
{:else if node.type === 'button'}<Button {node} />
{:else if node.type === 'meter'}<Meter {node} />
{/if}

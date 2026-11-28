
<script lang="ts">
    import type { UiNode } from './validate';
    import Badge from './Badge.svelte';
    import Button from './Button.svelte';
    import CodeBlock from './CodeBlock.svelte';
    import EmptyState from './EmptyState.svelte';
    import Form from './Form.svelte';
    import Input from './Input.svelte';
    import Layout from './Layout.svelte';
    import List from './List.svelte';
    import MarkdownSafe from './MarkdownSafe.svelte';
    import Meter from './Meter.svelte';
    import Progress from './Progress.svelte';
    import Section from './Section.svelte';
    import SelectNode from './SelectNode.svelte';
    import Sparkline from './Sparkline.svelte';
    import Stat from './Stat.svelte';
    import Table from './Table.svelte';
    import Tabs from './Tabs.svelte';
    import Text from './Text.svelte';
    import Textarea from './Textarea.svelte';
    import Toggle from './Toggle.svelte';

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
{:else if node.type === 'input'}<Input {node} />
{:else if node.type === 'textarea'}<Textarea {node} />
{:else if node.type === 'select'}<SelectNode {node} />
{:else if node.type === 'toggle'}<Toggle {node} />
{:else if node.type === 'tabs'}<Tabs {node} />
{:else if node.type === 'form'}<Form {node} />
{:else if node.type === 'code'}<CodeBlock {node} />
{:else if node.type === 'markdown_safe'}<MarkdownSafe {node} />
{:else if node.type === 'progress'}<Progress {node} />
{:else if node.type === 'empty_state'}<EmptyState {node} />
{:else if node.type === 'sparkline'}<Sparkline {node} />
{/if}

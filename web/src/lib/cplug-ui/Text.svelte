
<script lang="ts">
    import { useRender } from './context';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'text' }> } = $props();
    const ctx = useRender();
</script>

<p class="cu-text" data-cu="text" data-tone={node.tone ?? 'normal'}>{resolve(node.value, ctx.data)}</p>

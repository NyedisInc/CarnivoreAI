
<script lang="ts">
    import { useRender } from './context';
    import type { UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'badge' }> } = $props();
    const { t } = useRender();
</script>

<span class="cu-badge" data-cu="badge" data-tone={node.tone ?? 'normal'} data-status={node.status}>{node.status ? t(`cplug_ui.status.${node.status}`) : node.text}</span>

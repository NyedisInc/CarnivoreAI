
<script lang="ts">
    import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';

    const { id, icon, group, size = 24 }: { id: string; icon: string; group: string; size?: number } = $props();
</script>

<span class="wp-tile" data-group={group} style={`--tile-size: ${size}px; width: ${size}px; height: ${size}px`} aria-hidden="true"><WidgetIcon name={icon} widget={id} size={Math.round(size * 0.62)} /></span>

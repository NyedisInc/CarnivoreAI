
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import './byoai.css';
    import { markFor } from './provider-marks';

    interface Props {
        preset: string;
        size?: number;
    }
    const { preset, size = 16 }: Props = $props();
    const mark = $derived(markFor(preset));
</script>

<span class="ai-mark" data-ai-mark={preset} style:width="{size}px" style:height="{size}px">
    {#if 'paths' in mark}
        <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" aria-hidden="true" focusable="false">{@html mark.paths}</svg>
    {:else}
        <Icon name={mark.glyph} {size} />
    {/if}
</span>

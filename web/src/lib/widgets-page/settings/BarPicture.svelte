
<script lang="ts" module>
    import type { BarSize } from '../../widget-bars/bar-settings.svelte';
    import { barThickness } from '../../widget-bars/bar-size';
    import type { RailEdge } from '../../session-rail/rail-model';

    export type BarPose = BarSize | 'handle' | 'off';

    const SCALE = 0.3;
    const HANDLE_DRAWN_PX = 4;

    export function poseSize(edge: RailEdge, pose: BarPose): number {
        if (pose === 'off') return 0;
        return pose === 'handle' ? HANDLE_DRAWN_PX : barThickness(edge, pose) * SCALE;
    }
</script>

<script lang="ts">
    interface Props {
        side: BarPose;
        bottom: BarPose;
        dim?: boolean;
    }
    const { side, bottom, dim = false }: Props = $props();
    const sideW = $derived(poseSize('side', side));
    const bottomH = $derived(poseSize('bottom', bottom));
</script>

<span class="wp-mini" class:wp-mini--dim={dim} style:--mini-side="{sideW}px" style:--mini-bottom="{bottomH}px" aria-hidden="true">
    <span class="wp-mini__cells"><span class="wp-mini__cell"></span><span class="wp-mini__cell"></span></span>
    {#if side !== 'off'}
        <span class="wp-mini__bar wp-mini__bar--side" data-pose={side}>{#if side !== 'handle'}<i class="wp-mini__key"></i><i class="wp-mini__key"></i>{/if}</span>
    {/if}
    {#if bottom !== 'off'}
        <span class="wp-mini__bar wp-mini__bar--bottom" data-pose={bottom}>{#if bottom !== 'handle'}<i class="wp-mini__key"></i><i class="wp-mini__key"></i>{/if}</span>
    {/if}
</span>

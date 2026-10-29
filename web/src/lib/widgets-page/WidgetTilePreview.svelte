
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { WidgetManifest } from '../../opscenter/widgets/types';
    import { sizeNameKey } from '../../opscenter/widgets/named-sizes';
    import WidgetThumb from '../../opscenter/layout-editor/WidgetThumb.svelte';
    import PreviewFrame from './PreviewFrame.svelte';
    import { previewSizes, type PreviewSize } from './preview-sizes';
    import { trackPreview } from './preview-slots.svelte';
    import { useThemeKey } from './theme-key.svelte';

    interface Props {
        manifest: WidgetManifest;
        t: Translate;
        live?: boolean;
    }

    const { manifest, t, live = true }: Props = $props();

    const FIT_PAD = 0.92;
    const PREFERRED = ['wide', 'medium', 'small'];

    const theme = useThemeKey();
    let well: HTMLElement | undefined = $state();
    let granted = $state(false);
    let wellWidth = $state(0);
    let wellHeight = $state(0);
    let painted = $state(false);

    const size = $derived.by((): PreviewSize | null => {
        const all = previewSizes(manifest);
        const home = all.filter((one) => one.zone === 'home');
        const pool = home.length > 0 ? home : all;
        for (const name of PREFERRED) {
            const hit = pool.find((one) => one.name === name);
            if (hit) return hit;
        }
        let best: PreviewSize | null = null;
        for (const one of pool) if (best === null || one.w * one.h < best.w * best.h) best = one;
        return best;
    });
    const scale = $derived(size && wellWidth > 2 && wellHeight > 2 ? Math.min(1, FIT_PAD * Math.min(wellWidth / size.w, wellHeight / size.h)) : 1);

    $effect(() => {
        if (!live || !well || !size) return;
        const el = well;
        return trackPreview(el, (on) => {
            if (on) {
                wellWidth = el.clientWidth;
                wellHeight = el.clientHeight;
            } else painted = false;
            granted = on;
        });
    });

    function whenLoaded(frame: HTMLIFrameElement): () => void {
        const done = (): void => { painted = true; };
        frame.addEventListener('load', done, { once: true });
        return () => frame.removeEventListener('load', done);
    }
</script>

<div class="wp-tile__well" bind:this={well} data-thumb-state={granted ? 'live' : 'thumb'}>
    <div class="wp-tile__under" class:wp-tile__under--hidden={granted && painted}><WidgetThumb {manifest} wide /></div>
    {#if granted && size}
        {#key theme.value}
          <span class="wp-tile__stage" class:wp-tile__stage--ready={painted} style={`width:${Math.round(size.w * scale)}px;height:${Math.round(size.h * scale)}px`}>
            <PreviewFrame
                tile
                title={t('widgets.page.preview.frame', { title: t(manifest.titleKey), size: t(sizeNameKey(size.name)) })}
                {size}
                mode="sample"
                theme={theme.value}
                {scale}
                attach={whenLoaded}
            />
          </span>
        {/key}
    {/if}
</div>

<style>
    @layer components {
        .wp-tile__stage {
            position: relative;
            display: block;
            flex: none;
            overflow: hidden;
            opacity: 0;
        }

        .wp-tile__stage--ready {
            opacity: 1;
        }

        .wp-tile__well {
            position: absolute;
            inset: 0;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .wp-tile__under {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .wp-tile__under--hidden {
            visibility: hidden;
        }
    }
</style>

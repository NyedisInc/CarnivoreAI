
<script lang="ts">
    import { onDestroy } from 'svelte';
    import type { Translate } from '../sessions/types';
    import type { WidgetManifest } from '../../opscenter/widgets/types';
    import { sizeNameKey, type WidgetSizeName } from '../../opscenter/widgets/named-sizes';
    import { HERO_MAX_SCALE, previewSizes } from './preview-sizes';
    import { createPreviewProxy } from './preview-proxy';
    import { PREVIEW_PORT_MESSAGE, type PreviewMode, type PreviewRequest } from '../../widget-preview/protocol';
    import PreviewFrame from './PreviewFrame.svelte';
    import { useThemeKey } from './theme-key.svelte';

    interface Props {
        manifest: WidgetManifest;
        size: WidgetSizeName;
        mode: PreviewMode;
        t: Translate;
    }

    const { manifest, size, mode, t }: Props = $props();

    let width = $state(0);
    let height = $state(0);
    let stage = $state<HTMLElement | undefined>();
    const theme = useThemeKey();
    const box = $derived(previewSizes(manifest).find((one) => one.name === size) ?? null);
    const scale = $derived(box && width > 2 && height > 2 ? 0.92 * Math.min(HERO_MAX_SCALE, (width - 2) / box.w, (height - 2) / box.h) : 1);
    const proxy = createPreviewProxy();
    const ports = new Set<MessagePort>();

    function connect(frame: HTMLIFrameElement): () => void {
        const channel = new MessageChannel();
        ports.add(channel.port1);
        channel.port1.onmessage = (event: MessageEvent<PreviewRequest>) => {
            void proxy.answer(event.data).then((answer) => channel.port1.postMessage(answer));
        };
        const send = (): void => frame.contentWindow?.postMessage({ type: PREVIEW_PORT_MESSAGE }, location.origin, [channel.port2]);
        frame.addEventListener('load', send, { once: true });
        return () => {
            frame.removeEventListener('load', send);
            channel.port1.close();
            ports.delete(channel.port1);
        };
    }

    $effect(() => {
        if (!stage || typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(() => {
            width = stage?.clientWidth ?? 0;
            height = stage?.clientHeight ?? 0;
        });
        observer.observe(stage);
        return () => observer.disconnect();
    });

    onDestroy(() => {
        for (const port of ports) port.close();
        ports.clear();
    });
</script>

<div class="wp-hero__stage" bind:this={stage} data-widget-previews={manifest.id} data-preview-mode={mode} data-preview-size={size}>
    {#if box}
        <div class="wp-hero__well" style={`width:${Math.round(box.w * scale)}px;height:${Math.round(box.h * scale)}px`}>
            {#key `${manifest.id}:${size}:${mode}:${theme.value ?? ''}`}
                <PreviewFrame
                    title={t('widgets.page.preview.frame', { title: t(manifest.titleKey), size: t(sizeNameKey(size)) })}
                    size={box}
                    {mode}
                    theme={theme.value}
                    {scale}
                    attach={connect}
                />
            {/key}
        </div>
    {:else}
        <p class="wp-hero__none">{t('widgets.page.preview.none')}</p>
    {/if}
</div>

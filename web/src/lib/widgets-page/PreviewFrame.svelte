
<script lang="ts">
    import type { Attachment } from 'svelte/attachments';
    import { previewDocument, type PreviewMode } from '../../widget-preview/protocol';
    import type { PreviewSize } from './preview-sizes';

    interface Props {
        title: string;
        size: PreviewSize;
        mode: PreviewMode;
        theme: string | null;
        scale: number;
        attach?: Attachment<HTMLIFrameElement>;
        tile?: boolean;
    }

    const { title, size, mode, theme, scale, attach, tile = false }: Props = $props();
</script>

<iframe
    class="wp-pframe"
    {title}
    srcdoc={previewDocument({ key: size.key, zone: size.zone, size: { name: size.name, w: size.w, h: size.h }, mode, theme })}
    width={size.w}
    height={size.h}
    style={`transform:scale(${scale})`}
    tabindex="-1"
    inert
    aria-hidden={tile ? 'true' : undefined}
    data-wp-tile-preview={tile ? '' : undefined}
    {@attach attach}
></iframe>

<style>
    @layer components {
        .wp-pframe {
            position: absolute;
            inset: 0 auto auto 0;
            display: block;
            border: 0;
            transform-origin: 0 0;
            background: transparent;
            pointer-events: none;
        }
    }
</style>

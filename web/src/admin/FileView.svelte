
<script lang="ts">
    import type { SubmissionFile } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { file }: { file: SubmissionFile } = $props();
    let canvas: HTMLCanvasElement | undefined = $state();
    let drawn = $state(false);

    $effect(() => {
        if (file.kind !== 'image' || !file.data || !canvas || typeof createImageBitmap !== 'function') return;
        const target = canvas;
        const bytes = Uint8Array.from(atob(file.data), (c) => c.charCodeAt(0));
        void createImageBitmap(new Blob([bytes], { type: file.type }))
            .then((bitmap) => {
                const scale = Math.min(1, 480 / bitmap.width);
                target.width = Math.round(bitmap.width * scale);
                target.height = Math.round(bitmap.height * scale);
                target.getContext('2d')?.drawImage(bitmap, 0, 0, target.width, target.height);
                bitmap.close();
                drawn = true;
            })
            .catch(() => (drawn = false));
    });
</script>

{#if file.kind === 'text'}
    <pre class="admin-note-text">{file.text}</pre>
{:else}
    {#if file.data}
        <canvas bind:this={canvas} class="admin-preview" hidden={!drawn}></canvas>
    {/if}
    <p class="admin-note">{t(ADMIN_KEYS.detailImage, { type: file.type, size: file.size })}</p>
{/if}


<script module lang="ts">
    import { authFetchBlob } from '../../opscenter/api/auth.svelte';

    const cache = new Map<string, { path: string; url: Promise<string | null> }>();

    function imageUrl(path: string): Promise<string | null> {
        const id = path.split('?', 1)[0] ?? path;
        const held = cache.get(id);
        if (held?.path === path) return held.url;
        void held?.url.then((old) => {
            if (old) URL.revokeObjectURL(old);
        });
        const url = authFetchBlob(path).then(
            (blob) => URL.createObjectURL(blob),
            () => null,
        );
        cache.set(id, { path, url });
        return url;
    }
</script>

<script lang="ts">
    interface Props {
        path: string;
    }

    const { path }: Props = $props();

    let url = $state<string | null>(null);

    $effect(() => {
        const wanted = path;
        let live = true;
        url = null;
        void imageUrl(wanted).then((found) => {
            if (live) url = found;
        });
        return () => {
            live = false;
        };
    });
</script>

{#if url}
    <img class="oc-card-media__img" src={url} alt="" aria-hidden="true" draggable="false" data-card-media-img />
{/if}


<script lang="ts">
    import { catalogMediaUrl } from './card-media';

    interface Props {
        sha: string | null;
        previewUrl?: string | null;
    }

    const { sha, previewUrl = null }: Props = $props();

    let url = $state<string | null>(null);

    $effect(() => {
        const wanted = sha;
        let live = true;
        url = null;
        if (!wanted) return;
        void catalogMediaUrl(wanted).then((found) => {
            if (!live) return;
            url = found;
        });
        return () => {
            live = false;
        };
    });
</script>

{#if previewUrl ?? url}
    <img class="oc-card-media__img" src={previewUrl ?? url} alt="" aria-hidden="true" draggable="false" data-card-media-img />
{/if}

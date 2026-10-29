
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { authFetchBlob } from '../../opscenter/api/auth.svelte';
    import { kindIcon } from '../catalog/card';
    import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';

    interface Props { sha: string; kind: string; t: Translate }
    const { sha, kind, t }: Props = $props();

    let url = $state<string | null>(null);

    $effect(() => {
        let made: string | null = null;
        let live = true;
        url = null;
        authFetchBlob(`/catalog/publish/images/${encodeURIComponent(sha)}`)
            .then((blob) => {
                if (!live || !blob.type.startsWith('image/')) return;
                made = URL.createObjectURL(blob);
                url = made;
            })
            .catch(() => undefined);
        return () => {
            live = false;
            if (made) URL.revokeObjectURL(made);
        };
    });
</script>

{#if url}
    <img class="pp-card-img" src={url} alt="" draggable="false" />
{:else}
    <span class="pp-glyph" data-kind={kind} role="img" aria-label={kindLabel(kind, t) ?? kind}><Icon name={kindIcon(kind) ?? 'grid'} size={36} strokeWidth={1.75} /></span>
{/if}

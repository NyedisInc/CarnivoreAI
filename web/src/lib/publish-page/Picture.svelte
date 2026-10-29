
<script lang="ts">
    import { kindIcon } from '../catalog/card';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import CardArt from './CardArt.svelte';
    import SentImage from './SentImage.svelte';

    interface Props {
        picture: 'url' | 'art' | 'sent' | 'glyph';
        url: string | null;
        sha?: string | null;
        kind: string;
        name: string;
        t: Translate;
    }
    const { picture, url, sha = null, kind, name, t }: Props = $props();
</script>

{#if picture === 'url' && url}
    <img class="pp-card-img" src={url} alt="" draggable="false" />
{:else if picture === 'sent' && sha}
    <SentImage {sha} {kind} {t} />
{:else if picture === 'art'}
    <CardArt {kind} {name} />
{:else}
    <span class="pp-glyph" data-kind={kind} role="img" aria-label={kindLabel(kind, t) ?? kind}><Icon name={kindIcon(kind) ?? 'grid'} size={36} strokeWidth={1.75} /></span>
{/if}

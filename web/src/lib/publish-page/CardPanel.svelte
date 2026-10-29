
<script lang="ts">
    import WarezCard from '../catalog/WarezCard.svelte';
    import type { ItemRecord } from './list-model';
    import Panel from './Panel.svelte';
    import Picture from './Picture.svelte';
    import type { PageProps } from './props';
    import ReplaceImage from './ReplaceImage.svelte';
    import { cardViewOf } from './side-data';
    import './side.css';

    interface Props extends PageProps { rec: ItemRecord }
    const { store, actions, t, rec }: Props = $props();

    const card = $derived(cardViewOf(store, rec, t));
    const owner = $derived(store.account?.handle || t('publish.page.card.owner_fallback'));
</script>

<Panel label={t('publish.page.card.label')}>
    <WarezCard kind={card.kind} {t} name={t('publish.page.card.title', { owner, name: rec.name })} brief={rec.folder?.description ?? ''}>
        {#snippet thumb()}<Picture picture={card.picture} url={card.url} sha={card.sha} kind={card.kind} name={rec.name} {t} />{/snippet}
    </WarezCard>
    <p class="d-card__src" data-state={card.state}>{card.source}</p>
    {#if card.replaceable}
        <ReplaceImage {store} {actions} {t} location={rec.location} kind={rec.kind} name={rec.name} label="publish.page.card.replace" />
    {/if}
</Panel>

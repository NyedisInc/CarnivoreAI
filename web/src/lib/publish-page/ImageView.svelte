
<script lang="ts">
    import { selectedRecord } from './item-model';
    import Panel from './Panel.svelte';
    import Picture from './Picture.svelte';
    import type { PageProps } from './props';
    import ReplaceImage from './ReplaceImage.svelte';
    import { cardViewOf, timelineOf } from './side-data';
    import { clockText, dateText } from './format';
    import './detail.css';
    import './side.css';
    import './wizard.css';

    const { store, actions, t }: PageProps = $props();

    const rec = $derived(selectedRecord(store));
    const card = $derived(rec ? cardViewOf(store, rec, t) : null);
    const entry = $derived.by(() => {
        if (!rec || !store.mid) return null;
        const found = timelineOf(store, rec, t, false).find((i) => i.kind === 'entry' && i.key === store.mid?.ev);
        return found && found.kind === 'entry' ? found : null;
    });
    const lead = $derived.by((): string => {
        if (!card) return '';
        switch (card.state) {
            case 'making': return t('publish.page.image_view.generating');
            case 'failed': return t('publish.new.hero_failed');
            case 'rejected': return card.source;
            default: return t(card.picture === 'art' ? 'publish.page.image_view.made' : 'publish.page.image_view.chosen');
        }
    });
</script>

<div class="pp-iv" data-pp="ImageView">
    {#if rec && card}
        <h2 class="d-name">{t('publish.page.image_view.title')}</h2>
        <p class="d-kind">
            <span>{entry?.title ?? card.source}</span>
            {#if entry}<span>{dateText(entry.ts, t)} {clockText(entry.ts, t)}</span>{/if}
        </p>
        <Panel label={t('publish.page.image_view.picture')}>
            <div class="d-big"><div class="pp-hero-frame"><Picture picture={card.picture} url={card.url} sha={card.sha} kind={card.kind} name={rec.name} {t} /></div></div>
            <p class="d-lead">{lead}</p>
            <ReplaceImage {store} {actions} {t} location={rec.location} kind={rec.kind} name={rec.name} label={card.state === 'failed' ? 'publish.page.card.add' : 'publish.page.card.replace'} />
        </Panel>
    {/if}
</div>

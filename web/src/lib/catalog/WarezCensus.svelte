
<script lang="ts">
    import HighlightPair from '../../opscenter/ui/HighlightPair.svelte';
    import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
    import type { Translate } from '../sessions/types';
    import { mostDownloaded, newestItems } from './census';
    import { displayKind } from './kind-display';
    import type { CatalogItem } from './types';

    interface Props {
        items: readonly CatalogItem[];
        kind?: string | null;
        installs: ReadonlyMap<string, number>;
        t: Translate;
    }

    const { items: allItems, kind = null, installs, t }: Props = $props();
    const items = $derived(kind ? allItems.filter((item) => item.kind === kind) : allItems);

    const kindLabel = (kind: string): string => t(`warez.kind.chip.${kind}`);
    const name = (item: CatalogItem): string => item.card?.title || item.name || item.id || '';
    const newest = $derived<RankRow[]>(
        newestItems(items).map((item) => ({
            id: item.id ?? name(item),
            name: name(item),
            tags: displayKind(item.kind) ? [kindLabel(displayKind(item.kind)!)] : [],
            metric: { value: (item.first_published_at ?? '').slice(0, 10) },
        })),
    );
    const downloaded = $derived<RankRow[]>(
        mostDownloaded(items, installs).map(({ item, count }) => ({
            id: item.id ?? name(item),
            name: name(item),
            tags: displayKind(item.kind) ? [kindLabel(displayKind(item.kind)!)] : [],
            metric: { value: String(count), unit: t('warez.hl.installs') },
        })),
    );
</script>

{#if newest.length > 0}
    <div class="wz-census" data-warez-census>
        {#snippet first()}
            <RankPanel
                label={t('warez.hl.newest')}
                rows={newest}
                ranked
                columns={{ name: t('warez.hl.col.item'), metric: t('warez.hl.col.first_published') }}
                notMeasured={t('warez.hl.not_measured')}
                empty={t('warez.hl.not_measured')}
            />
        {/snippet}
        {#snippet second()}
            <RankPanel
                label={t('warez.hl.downloaded')}
                rows={downloaded}
                ranked
                columns={{ name: t('warez.hl.col.item'), metric: t('warez.hl.col.installs') }}
                notMeasured={t('warez.hl.not_measured')}
                empty={t('warez.hl.not_measured')}
            />
        {/snippet}
        {#if downloaded.length > 0}
            <HighlightPair label={t('warez.hl.pair')} caption={t('warez.hl.pair_caption')} {first} {second} />
        {:else}
            
            {@render first()}
        {/if}
    </div>
{/if}

<style>
    @layer components {
        .wz-census {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            padding-inline: var(--oc-page-gutter, 16px);
            margin-bottom: var(--oc-space-4, 16px);
            min-width: 0;
        }
    }
</style>

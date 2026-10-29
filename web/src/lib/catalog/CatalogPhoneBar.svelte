
<script lang="ts">
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import { sortOptions } from './filter-groups';
    import type { SortKey } from './sort';
    import WarezActs from './WarezActs.svelte';
    import { isReadonly } from './readonly';

    interface Props {
        sortKey: SortKey;
        onSort: (next: SortKey) => void;
        refreshing: boolean;
        onRefresh: () => void;
        onPublish: () => void;
        t: Translate;
    }

    const { sortKey, onSort, refreshing, onRefresh, onPublish, t }: Props = $props();
    const readonly = isReadonly();
</script>

<div class="catalog-phonebar">
    <div class="catalog-phonebar__row catalog-phonebar__row--pick">
        <FacetSelect id="sort" label={t(BROWSE_KEYS.sortLabel)} value={sortKey} options={sortOptions(t)} onChange={(next) => onSort(next as SortKey)} />
    </div>
    {#if !readonly}
    <div class="catalog-phonebar__row catalog-phonebar__row--tools">
        <WarezActs {refreshing} {onRefresh} {onPublish} {t} />
    </div>
    {/if}
</div>

<style>
    .catalog-phonebar {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
        padding: 8px 12px;
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .catalog-phonebar__row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        min-width: 0;
    }

    .catalog-phonebar__row--pick > :global(.oc-facet) {
        flex: 1 1 0;
        min-width: 0;
    }

    .catalog-phonebar__row--pick :global(.oc-facet__select) {
        min-width: 44px;
        height: calc(100% + 2px);
        margin-block: -1px;
    }

    .catalog-phonebar__row--tools {
        flex-wrap: nowrap;
    }

    .catalog-phonebar__row--tools > :global(.warez-act) {
        flex: 1 1 auto;
        min-width: 44px;
        padding-inline: 8px;
    }

    .catalog-phonebar__row--tools :global(.keys-menu) {
        flex: none;
    }

    .catalog-phonebar__row--tools :global(.keys-menu .warez-act) {
        width: 44px;
        padding: 0;
    }
</style>

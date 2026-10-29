
<script lang="ts">
    import type { Snippet } from 'svelte';
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import ViewToggle from '../manager-frame/ViewToggle.svelte';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { ManagerView } from '../manager-frame/view-memory';
    import type { Translate } from '../sessions/types';
    import { sortOptions } from './filter-groups';
    import type { SortKey } from './sort';

    interface Props {
        search: Snippet;
        sortKey: SortKey;
        onSort: (next: SortKey) => void;
        view: ManagerView;
        onView: (next: ManagerView) => void;
        arrange?: boolean;
        t: Translate;
    }

    const { search, sortKey, onSort, view, onView, arrange = true, t }: Props = $props();
</script>

<div class="wtools" role="search">
    <div class="wtools__search">{@render search()}</div>
    {#if arrange}
        <FacetSelect id="sort" label={t(BROWSE_KEYS.sortLabel)} value={sortKey} options={sortOptions(t)} onChange={(next) => onSort(next as SortKey)} />
        <ViewToggle {view} {onView} {t} />
    {/if}
</div>

<style>
    .wtools {
        display: flex;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .wtools__search {
        flex: none;
        width: 236px;
    }

    .wtools__search :global(.oc-field) {
        height: var(--oc-rowheight, 26px);
        padding-block: 0;
        padding-inline: 8px;
        font-size: 12px;
    }

    .wtools :global(.oc-facet) {
        gap: 0;
        padding: 0;
        border-color: var(--oc-line-panel);
        border-radius: 2px;
        background: transparent;
        overflow: hidden;
    }

    .wtools :global(.oc-facet__key) {
        align-self: stretch;
        display: flex;
        align-items: center;
        margin-right: 10px;
        padding: 0 8px;
        background: var(--oc-ground-titlerow);
        box-shadow: inset -1px 0 0 0 var(--oc-line-panel);
        font-size: 10px;
        letter-spacing: 0.6px;
        text-transform: uppercase;
    }

    .wtools :global(.oc-facet__key::after) {
        content: none;
    }

    .wtools :global(.oc-facet > svg) {
        margin: 0 9px 0 2px;
    }

    .wtools :global(.oc-facet__select) {
        field-sizing: content;
    }

    .wtools :global(.oc-page__view) {
        gap: 0;
        margin-left: 0;
        border: 1px solid var(--oc-line-panel);
        border-radius: 2px;
        overflow: hidden;
        font-size: 12px;
    }

    .wtools :global(.oc-page__view .oc-ibtn) {
        --oc-ibtn-size: var(--oc-rowheight, 26px);
        width: 32px;
        border: 0;
        border-left: 1px solid var(--oc-line-panel);
        border-radius: 0;
        background: transparent;
    }

    .wtools :global(.oc-page__view .oc-ibtn:first-child) {
        border-left: 0;
    }

    .wtools :global(.oc-page__view .oc-ibtn:hover) {
        background: var(--oc-ground-hover);
    }

    .wtools :global(.oc-page__view .oc-ibtn[aria-pressed='true']) {
        background: var(--oc-orange-tint);
        color: var(--oc-text-bright);
    }
</style>

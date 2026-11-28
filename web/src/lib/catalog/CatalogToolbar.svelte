
<script lang="ts">
    import './catalog-phone-bar.css';
    import type { Translate } from '../sessions/types';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { CatalogFilters } from './filter';
    import { stateOf, withState, pressOrClear, kindChipsFor, STATE_SEGMENTS, stateTip, type StateGroup } from './filter-groups';
    import KindMark from './KindMark.svelte';
    import Segmented, { type SegmentedOption } from '../base/Segmented.svelte';

    interface Props {
        filters: CatalogFilters;
        kinds: readonly string[];
        t: Translate;
        onFilters: (next: CatalogFilters) => void;
    }

    const { filters, kinds, t, onFilters }: Props = $props();

    const kindChips = $derived(kindChipsFor(kinds, filters.kind, t));
    const tip = (value: string): string => stateTip(value, t);

    const state = $derived(stateOf(filters));

    const ALL_KINDS = '__all';

    const kindOptions = $derived<SegmentedOption[]>([
        { value: ALL_KINDS, label: t(BROWSE_KEYS.kindChipAll) },
        ...kindChips.map((chip) => ({ value: chip.kind, label: chip.label, mark: kindMark, attrs: { 'data-kind': chip.kind } })),
    ]);

    const stateOptions = $derived<SegmentedOption[]>(STATE_SEGMENTS.map(([value, key]) => ({ value, label: t(key), title: tip(value) })));

    function pickKind(kind: string | null): void {
        onFilters({ ...filters, kind });
    }

    function pickState(next: string): void {
        const group = STATE_SEGMENTS.find(([value]) => value === next)?.[0];
        if (group) onFilters(withState(filters, pressOrClear<StateGroup>(state, group)));
    }

</script>

{#snippet kindMark(kind: string)}
    {#if kind !== ALL_KINDS}<KindMark {kind} size="sm" {t} />{/if}
{/snippet}

{#snippet kindGroup()}
    {#if kindChips.length}
        <Segmented
            data-group="kind"
            caption={t('warez.group.kind')}
            label={t('warez.group.kind')}
            value={filters.kind ?? ALL_KINDS}
            options={kindOptions}
            onchange={(next) => pickKind(next === ALL_KINDS ? null : next)}
        />
    {/if}
{/snippet}

{#snippet stateGroup()}
    <Segmented
        data-group="state"
        caption={t('warez.group.state')}
        label={t('warez.group.state')}
        value={state}
        options={stateOptions}
        onchange={pickState}
        onreselect={pickState}
    />
{/snippet}

<div class="cat-rows">
    {@render kindGroup()}
    {@render stateGroup()}
</div>

<style>
    .cat-rows {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        min-width: 0;
        padding: 4px 12px;
    }
</style>

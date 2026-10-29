
<script lang="ts">
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Select from '../base/Select.svelte';
    import type { Translate } from '../sessions/types';
    import { measureHeadingKey, type LensKey } from './lenses';
    import { COLUMNS, ariaSort, type ColumnKey, type SortState } from './sorting';

    interface Props {
        sort: SortState | null;
        lens: LensKey;
        t: Translate;
        onSort: (k: ColumnKey | null) => void;
        onReverse: () => void;
    }
    const { sort, lens, t, onSort, onReverse }: Props = $props();

    const CELL: Readonly<Record<ColumnKey, string>> = { name: 'sp-c-name', state: 'sp-c-state', proj: 'sp-c-proj', prov: 'sp-c-prov', latest: 'sp-c-latest', measure: 'sp-c-measure', comp: 'sp-c-comp', start: 'sp-c-start' };

    const label = (k: ColumnKey): string => t(k === 'measure' ? measureHeadingKey(lens) : `sessions.page.col.${k}`);
    const phoneDir = $derived(sort ? (ariaSort(sort, sort.k) === 'ascending' ? 'up' : 'down') : 'up');
</script>

<div class="sp-lhead" role="row">
    <span class="sp-lh-spacer"></span>
    <div class="sp-l1">
        {#each COLUMNS as k (k)}
            {@const dir = ariaSort(sort, k)}
            <span class="sp-hcw {CELL[k]}">
                <Button variant="quiet" size="sm" data-sort={k} aria-sort={dir ?? undefined} onclick={() => onSort(k)}>
                    <span>{label(k)}</span>{#if dir}<i class="sp-arr"></i>{/if}
                </Button>
            </span>
        {/each}
    </div>
    <div class="sp-lh-m">
        <span class="pl-label">{t('sessions.page.sort.label')}</span>
        <Select size="sm" aria-label={t('sessions.page.sort.by')} value={sort?.k ?? ''} onchange={(e) => onSort((e.currentTarget.value || null) as ColumnKey | null)}
            options={[...(sort ? [] : [{ value: '', label: t('sessions.page.sort.none') }]), ...COLUMNS.map((k) => ({ value: k, label: label(k) }))]} />
        <IconButton data-dir label={t('sessions.page.sort.reverse')} disabled={!sort} onclick={onReverse}>
            {#snippet children()}<i class="sp-arr" data-d={phoneDir}></i>{/snippet}
        </IconButton>
    </div>
</div>

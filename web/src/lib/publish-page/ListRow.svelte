
<script lang="ts">
    import { buttonAttrs } from '../base/classes';
    import type { Translate } from '../sessions/types';
    import KindMark from '../catalog/KindMark.svelte';
    import { pageRowMenu, type PageRowMenu } from '../item-menu/page-row';
    import { dateText } from './format';
    import { markKind, type RowData } from './list-model';
    import StageMark from './StageMark.svelte';

    interface Props {
        row: RowData;
        selected: boolean;
        changed: boolean;
        submissions: boolean;
        t: Translate;
        onPick: () => void;
        menu: () => PageRowMenu | null;
        onFlashEnd: () => void;
    }
    const { row, selected, changed, submissions, t, onPick, menu, onFlashEnd }: Props = $props();

    const word = $derived(t(row.wordKey));
    const item = $derived(row.harness ? `${row.name} (${row.harness})` : row.name);
    const second = $derived(submissions && row.date ? t('publish.page.row.word_date', { word, date: dateText(row.date, t) }) : word);
    const label = $derived(submissions ? t('publish.page.row.aria_submission', { item, version: row.version, word }) : t('publish.page.row.aria_item', { item, word }));
    const aside = $derived([submissions ? row.version : '', row.harness].filter(Boolean).join(' '));
</script>

<li>
    <button
        type="button"
        class="d-row"
        {...buttonAttrs('row', 'md')}
        class:d-row--changed={changed}
        data-loc={row.location}
        data-sub={row.subId ?? undefined}
        data-wait={row.wait ? 1 : 0}
        aria-current={selected ? 'true' : 'false'}
        aria-label={label}
        onclick={onPick}
        onanimationend={onFlashEnd}
        {...pageRowMenu(menu)}
    >
        <span class="d-row__m"><KindMark kind={markKind(row.kind)} size="md" bare {t} /></span>
        <span class="d-row__t">
            <span class="d-row__n"><span class="d-row__nm">{row.name}</span>{#if aside}<span class="d-row__h">{aside}</span>{/if}</span>
            <span class="d-row__s">{second}</span>
        </span>
        {#if row.stage}<StageMark stage={row.stage} shapeOnly {t} />{:else}<span aria-hidden="true"></span>{/if}
    </button>
</li>

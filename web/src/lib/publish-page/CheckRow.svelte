
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import { buttonAttrs } from '../base/classes';
    import type { Translate } from '../sessions/types';
    import Ident from './Ident.svelte';
    import CheckMark from './CheckMark.svelte';
    import { shownFindings, type CheckCell } from './checks-model';
    import { findingSentence, gateLabelKey, gateLooksAtKey, resultKey } from './report-format';
    import './checks.css';

    interface Props {
        cell: CheckCell;
        expanded: boolean;
        all: boolean;
        t: Translate;
        onToggle: () => void;
        onMore: () => void;
    }
    const { cell, expanded, all, t, onToggle, onMore }: Props = $props();
    const finds = $derived(shownFindings(cell.findings, all));
</script>

<li class="d-chk__row" data-result={cell.result} data-pp="CheckRow" data-gate={cell.id}>
    <button type="button" class="d-chk__h" {...buttonAttrs('row', 'md')} aria-expanded={expanded} onclick={onToggle}>
        <CheckMark result={cell.result} shapeOnly />
        <span class="d-chk__n pp-ident">{t(gateLabelKey(cell.id))}</span>
        <span class="d-chk__v">{t(resultKey(cell.result))}</span>
        <span class="d-chk__c" aria-hidden="true"><Icon name={expanded ? 'chevron-down' : 'chevron-right'} size={12} /></span>
    </button>
    {#if expanded}
        <div class="d-chk__b">
            <p class="d-chk__what">{t('publish.page.checks.looks_at', { sentence: t(gateLooksAtKey(cell.id)) })}</p>
            {#if finds.shown.length}
                <ul class="d-chk__f">
                    {#each finds.shown as finding, i (i)}<li class="pp-ident"><Ident text={findingSentence(finding, t)} /></li>{/each}
                </ul>
                {#if finds.hidden > 0}
                    <span class="d-more"><Button size="sm" onclick={onMore}>{t('publish.page.checks.show_more', { count: finds.hidden })}</Button></span>
                {/if}
            {/if}
            {#if cell.fix}<p class="d-fix">{t('skill.publish.report.fix', { fix: cell.fix })}</p>{/if}
        </div>
    {/if}
</li>

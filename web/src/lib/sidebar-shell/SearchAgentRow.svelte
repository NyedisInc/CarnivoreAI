
<script lang="ts">
    import SessionFace from '../sessions/SessionFace.svelte';
    import ConvLed from '../deepsearch/ConvLed.svelte';
    import { t } from '../i18n/index.svelte';
    import { searchD } from '../drawer/search-d.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import ModelMark from './ModelMark.svelte';
    import RowActions from './RowActions.svelte';
    import RowMenuTrigger from './RowMenuTrigger.svelte';
    import RowWakeArm from './RowWakeArm.svelte';
    import { isRowEditing } from './row-rename';
    import type { SearchHitPlan, SessionRowPlan } from './row-plan';
    import { disarmWake, isWakeArmed, markArmable, wakeArmable } from './wake-arm.svelte';
    import '../deepsearch/search-d.css';
    import './search-sections.css';

    let { p }: { p: SessionRowPlan } = $props();
    const search = $derived(p.search as SearchHitPlan);

    const rowName = $derived(p.attrs['data-name'] || '');
    const rowBand = $derived(p.attrs['data-band']);
    const editing = $derived(isRowEditing(rowName, rowBand));
    const facts = $derived(search.facts);
    const armable = $derived(wakeArmable(p.led, p.ghost));
    const armed = $derived(armable && isWakeArmed(rowName, rowBand));
    $effect(() => { if (!armable && isWakeArmed(rowName, rowBand)) disarmWake(); });
    $effect(() => () => { if (isWakeArmed(rowName, rowBand)) disarmWake(); });
    const cursor = $derived(searchD.agentNames[searchD.cursor] === rowName ? '1' : undefined);
    function inertWhenArmed(el: HTMLElement): (() => void) | void {
        if (!armed) return;
        el.setAttribute('inert', '');
        return () => el.removeAttribute('inert');
    }
</script>

{#snippet marked(parts: { before: string; match: string; after: string })}{parts.before}{#if parts.match}<mark class="sd-mark">{parts.match}</mark>{/if}{parts.after}{/snippet}
<div {...p.attrs} class="session-sidebar-row ssr-row sd-r" data-editing={editing ? '1' : undefined} data-wake-armed={armed ? '1' : undefined} data-search-cursor={cursor} {@attach markArmable(armable)}><div class="sd-r__body" {@attach inertWhenArmed}><div class="sd-r__top">{#if p.led}<SessionFace bare facts={{ family: null, ...p.led }} />{:else}<ConvLed kind="ring" live={undefined} title={facts.note ?? t('session.closed.label')} />{/if}<span {...p.name.attrs} hidden={editing}>{@render marked(search.name.match ? search.name : { before: p.name.text, match: '', after: '' })}</span>{#if editing}<HeadingRenameEditor />{/if}{#if facts.age}<span class="sd-r__meta">{facts.age}</span>{/if}<RowActions actions={p.actions} />{#if p.menu}<RowMenuTrigger spec={p.menu} />{/if}</div>{#if facts.note || facts.model || facts.effort}<div class="sd-r__sub">{#if facts.note}<span class="sd-dim">{facts.note}</span>{:else}{#if facts.model}<ModelMark model={facts.model} />{/if}{#if facts.modelName}<span>{facts.modelName}</span>{/if}{#if facts.effort}<span class="sd-dim">{facts.effort}</span>{/if}{/if}</div>{/if}{#if search.context}<div class="sd-r__sub sd-why"><span>{#if search.context.project}{@render marked(search.context.project)}{/if}{#if search.context.project && search.context.folder}<span class="sd-dim"> · </span>{/if}{#if search.context.folder}{@render marked(search.context.folder)}{/if}</span></div>{/if}</div>{#if armed}<RowWakeArm name={p.name.text} />{/if}</div>

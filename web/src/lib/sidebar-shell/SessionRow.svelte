
<script lang="ts">
    import { kebabSvg } from './kebab';
    import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import MessagingBadge from '../messaging/MessagingBadge.svelte';
    import BadgeSlot from '../session-badges/BadgeSlot.svelte';
    import { t } from '../i18n/index.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import RowAvatar from './RowAvatar.svelte';
    import RowCozyBody from './RowCozyBody.svelte';
    import RowDetailedBody from './RowDetailedBody.svelte';
    import RowActions from './RowActions.svelte';
    import RowChip from './RowChip.svelte';
    import RowMenuTrigger from './RowMenuTrigger.svelte';
    import RowPin from './RowPin.svelte';
    import type { SessionRowPlan } from './row-plan';
    import { isRowEditing } from './row-rename';
    import RowWakeArm from './RowWakeArm.svelte';
    import { disarmWake, isWakeArmed, markArmable, wakeArmable } from './wake-arm.svelte';
    import { insigniaSvg } from './leaders';
    import { searchD } from '../drawer/search-d.svelte';
    import '../deepsearch/search-d.css';
    import './row-polish.css';
    import { openGhostMenu, openGhostTerminal } from './leader-ghost';
    import { buttonAttrs } from '../base/classes';

    let { p }: { p: SessionRowPlan } = $props();

    const editing = $derived(isRowEditing(p.attrs['data-name'] || '', p.attrs['data-band']));
    const rowName = $derived(p.attrs['data-name'] || '');
    const rowBand = $derived(p.attrs['data-band']);
    const rowUuid = $derived(p.attrs['data-session-uuid']);
    const armable = $derived(wakeArmable(p.led, p.ghost));
    const armed = $derived(armable && isWakeArmed(rowName, rowBand, rowUuid));
    $effect(() => { if (!armable && isWakeArmed(rowName, rowBand, rowUuid)) disarmWake(); });
    $effect(() => () => { if (isWakeArmed(rowName, rowBand, rowUuid)) disarmWake(); });
    const cursor = $derived(p.search && searchD.agentNames[searchD.cursor] === rowName ? '1' : undefined);
    function inertWhenArmed(el: HTMLElement): (() => void) | void {
        if (!armed) return;
        el.setAttribute('inert', '');
        return () => el.removeAttribute('inert');
    }
</script>

{#snippet marked(parts: { before: string; match: string; after: string })}{parts.before}{#if parts.match}<mark class="sd-mark">{parts.match}</mark>{/if}{parts.after}{/snippet}
{#snippet timerGlyph()}<svg class="timer-chip__glyph" viewBox="0 0 10 10" aria-hidden="true" focusable="false"><circle cx="5" cy="5" r="4"></circle><path d="M5 2.6V5l1.6 1"></path></svg>{/snippet}
<div {...p.attrs} onclick={(e) => { if (p.ghost) openGhostTerminal(e, p.ghost); }} data-editing={editing ? '1' : undefined} data-context-gauge={p.context && p.body?.mode !== 'detailed' ? '1' : undefined} data-row-body={p.body ? p.body.mode : undefined} data-row-flag={p.body?.flagTone ?? p.notice?.tone ?? undefined} data-wake-armed={armed ? '1' : undefined} data-search-cursor={cursor} {@attach markArmable(armable)}><div class="session-sidebar-row-main" {@attach inertWhenArmed}>{#if p.leader}<span class="session-sidebar-row-leader" data-leader-mark={p.leader.rank} role="img" aria-label={p.leader.label} title={p.leader.label}>{@html insigniaSvg(p.leader.rank)}</span>{/if}{#if p.led}<SessionFace bare facts={{ family: null, ...p.led }} member={p.member} />{/if}{#if p.cozySubagents}<RowChip chip={p.cozySubagents} />{/if}{#if p.cozyTimer}<RowChip chip={p.cozyTimer} lead={timerGlyph} />{/if}<RowAvatar provider={p.provider} model={p.model} leadHtml={p.leadHtml} asleep={p.attrs['data-asleep'] === '1'} size={p.body ? 'md' : 'sm'} />{#if p.archived}<RowChip chip={p.archived} />{/if}{#if p.closed}<RowChip chip={p.closed} />{/if}{#if p.offloaded}<RowChip chip={p.offloaded} />{/if}{#if p.detailedCount}<RowChip chip={p.detailedCount} />{/if}{#if p.detailedTimer}<RowChip chip={p.detailedTimer} lead={timerGlyph} />{/if}{#if p.body}<div class="sb-row-stack"><div class="sb-row-stack__top"><span {...p.name.attrs} hidden={editing}>{#if p.search?.name.match}{p.search.name.before}<mark class="sd-mark">{p.search.name.match}</mark>{p.search.name.after}{:else}{p.name.text}{/if}</span>{#if editing}<HeadingRenameEditor />{/if}{#if p.auto}<RowChip chip={p.auto} />{/if}{#if p.messaging}<MessagingBadge mark={p.messaging} />{/if}{#if p.subtitle}<RowChip chip={p.subtitle} />{/if}{#if p.body.rankTag}<span class="session-sidebar-row-badge session-row-body__rank">{p.body.rankTag}</span>{/if}{#if p.hostInline}<RowChip chip={p.hostInline} />{/if}{#if p.share}<RowChip chip={p.share} />{/if}{#if p.badges}<BadgeSlot plan={p.badges} />{/if}</div><RowCozyBody body={p.body} actions={p.actions} /></div>{:else}{#if p.auto}<RowChip chip={p.auto} />{/if}{#if p.messaging}<MessagingBadge mark={p.messaging} />{/if}<span {...p.name.attrs} hidden={editing}>{#if p.search?.name.match}{p.search.name.before}<mark class="sd-mark">{p.search.name.match}</mark>{p.search.name.after}{:else}{p.name.text}{/if}</span>{#if editing}<HeadingRenameEditor />{/if}{#if p.subtitle}<RowChip chip={p.subtitle} />{/if}{#if p.cozyBadge}<RowChip chip={p.cozyBadge} />{/if}{#if p.cozyWhen}<RowChip chip={p.cozyWhen} />{/if}{#if p.hostInline}<RowChip chip={p.hostInline} />{/if}{#if p.share}<RowChip chip={p.share} />{/if}{#if p.badges}<BadgeSlot plan={p.badges} />{/if}{/if}<span class="session-sidebar-row-controls-cluster">{#if p.agentsIcon || p.shellsIcon || p.timersIcon || p.automationsIcon}<span class="session-sidebar-row-optional-icons">{#if p.agentsIcon}<RowChip chip={p.agentsIcon} />{/if}{#if p.shellsIcon}<RowChip chip={p.shellsIcon} />{/if}{#if p.timersIcon}<RowChip chip={p.timersIcon} />{/if}{#if p.automationsIcon}<RowChip chip={p.automationsIcon} />{/if}</span>{/if}{#if p.keepAwake}<RowChip chip={p.keepAwake} />{/if}{#if p.restore}<RowChip chip={p.restore} />{/if}{#if p.wake}<RowChip chip={p.wake} />{/if}{#if p.workflow}<RowChip chip={p.workflow} />{/if}{#if p.pin}<RowPin attrs={p.pin} />{/if}{#if !p.body?.ended?.dead}<RowActions actions={p.actions} />{/if}{#if p.menu}<RowMenuTrigger spec={p.menu} />{/if}{#if p.ghost}{@const g = p.ghost}<button type="button" class="session-row-menu-trigger" data-ghost-menu aria-haspopup="menu" aria-label={t('leader.menu.label', { name: g.name })} data-tooltip="" tabindex="-1" onclick={(e) => { e.stopPropagation(); openGhostMenu(e.currentTarget, g); }}>{@html kebabSvg()}</button>{/if}</span></div>{#if p.meta}<div class="session-sidebar-row-meta">{#if p.meta.badge}<RowChip chip={p.meta.badge} />{/if}{#if p.meta.age}<RowChip chip={p.meta.age} />{/if}{#if p.meta.when}<RowChip chip={p.meta.when} />{/if}{#if p.meta.hint}<RowChip chip={p.meta.hint} />{/if}{#if p.meta.host}<RowChip chip={p.meta.host} />{/if}</div>{/if}{#if p.notice}<div class="session-row-body"><div class="session-row-body__line session-row-body__flag" data-flag={p.notice.kind} data-tone={p.notice.tone}><span class="session-row-body__flag-words">{p.notice.text}</span></div></div>{/if}{#if p.body?.mode === 'detailed' && !p.body.ended}<RowDetailedBody body={p.body} actions={p.actions} context={p.context} />{/if}{#if p.context && p.body?.mode !== 'detailed'}<LimitGauge class="session-sidebar-row-context" variant="fill" pct={p.context.pct} scale={p.context.scale} meterText={p.context.label} height={2} />{/if}{#if p.search?.context}<div class="sd-r__sub sd-why"><span>{#if p.search.context.project}{@render marked(p.search.context.project)}{/if}{#if p.search.context.project && p.search.context.folder}<span class="sd-dim"> · </span>{/if}{#if p.search.context.folder}{@render marked(p.search.context.folder)}{/if}</span></div>{/if}{#if armed}<RowWakeArm name={p.name.text} />{/if}</div>

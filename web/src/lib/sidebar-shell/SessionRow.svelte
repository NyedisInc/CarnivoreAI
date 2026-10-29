<!-- hidden -->
<script lang="ts">
    import { kebabSvg } from './kebab';
    import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import MessagingBadge from '../messaging/MessagingBadge.svelte';
    import { t } from '../i18n/index.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import ModelMark from './ModelMark.svelte';
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
    import './row-polish.css';
    import { openGhostMenu, openGhostTerminal } from './leader-ghost';
    import { buttonAttrs } from '../base/classes';

    let { p }: { p: SessionRowPlan } = $props();

    const editing = $derived(isRowEditing(p.attrs['data-name'] || '', p.attrs['data-band']));
    const rowName = $derived(p.attrs['data-name'] || '');
    const rowBand = $derived(p.attrs['data-band']);
    const armable = $derived(wakeArmable(p.led, p.ghost));
    const armed = $derived(armable && isWakeArmed(rowName, rowBand));
    $effect(() => { if (!armable && isWakeArmed(rowName, rowBand)) disarmWake(); });
    $effect(() => () => { if (isWakeArmed(rowName, rowBand)) disarmWake(); });
    function inertWhenArmed(el: HTMLElement): (() => void) | void {
        if (!armed) return;
        el.setAttribute('inert', '');
        return () => el.removeAttribute('inert');
    }
</script>

{#snippet timerGlyph()}<svg class="timer-chip__glyph" viewBox="0 0 10 10" aria-hidden="true" focusable="false"><circle cx="5" cy="5" r="4"></circle><path d="M5 2.6V5l1.6 1"></path></svg>{/snippet}
<div {...p.attrs} onclick={(e) => { if (p.ghost) openGhostTerminal(e, p.ghost); }} data-editing={editing ? '1' : undefined} data-context-gauge={p.context ? '1' : undefined} data-row-body={p.body ? p.body.mode : undefined} data-row-flag={p.body?.flagTone ?? undefined} data-wake-armed={armed ? '1' : undefined} {@attach markArmable(armable)}><div class="session-sidebar-row-main" {@attach inertWhenArmed}>{#if p.leader}<span class="session-sidebar-row-leader" data-leader-mark={p.leader.rank} role="img" aria-label={p.leader.label} title={p.leader.label}>{@html insigniaSvg(p.leader.rank)}</span>{/if}{#if p.led}<SessionFace bare facts={{ family: null, ...p.led }} />{/if}{#if p.cozySubagents}<RowChip chip={p.cozySubagents} />{/if}{#if p.cozyTimer}<RowChip chip={p.cozyTimer} lead={timerGlyph} />{/if}<RowChip chip={p.provider} />{#if p.archived}<RowChip chip={p.archived} />{/if}{#if p.closed}<RowChip chip={p.closed} />{/if}{#if p.auto}<RowChip chip={p.auto} />{/if}{#if p.messaging}<MessagingBadge mark={p.messaging} />{/if}{#if p.model}<ModelMark model={p.model} />{/if}{#if p.detailedCount}<RowChip chip={p.detailedCount} />{/if}{#if p.detailedTimer}<RowChip chip={p.detailedTimer} lead={timerGlyph} />{/if}<span {...p.name.attrs} hidden={editing}>{p.name.text}</span>{#if editing}<HeadingRenameEditor />{/if}{#if p.subtitle}<RowChip chip={p.subtitle} />{/if}{#if p.cozyBadge}<RowChip chip={p.cozyBadge} />{/if}{#if p.cozyWhen}<RowChip chip={p.cozyWhen} />{/if}{#if p.body?.rankTag}<span class="session-sidebar-row-badge session-row-body__rank">{p.body.rankTag}</span>{/if}{#if p.hostInline}<RowChip chip={p.hostInline} />{/if}{#if p.body?.right}<span class="session-row-body__right" data-kind={p.body.right.kind} data-tone={p.body.right.tone ?? undefined}>{p.body.right.text}</span>{/if}{#if p.share}<RowChip chip={p.share} />{/if}<span class="session-sidebar-row-controls-cluster">{#if p.agentsIcon || p.shellsIcon || p.timersIcon || p.automationsIcon}<span class="session-sidebar-row-optional-icons">{#if p.agentsIcon}<RowChip chip={p.agentsIcon} />{/if}{#if p.shellsIcon}<RowChip chip={p.shellsIcon} />{/if}{#if p.timersIcon}<RowChip chip={p.timersIcon} />{/if}{#if p.automationsIcon}<RowChip chip={p.automationsIcon} />{/if}</span>{/if}{#if p.keepAwake}<RowChip chip={p.keepAwake} />{/if}{#if p.wake}<RowChip chip={p.wake} />{/if}{#if p.workflow}<RowChip chip={p.workflow} />{/if}{#if p.pin}<RowPin attrs={p.pin} />{/if}{#if !p.body?.ended?.dead}<RowActions actions={p.actions} />{/if}{#if p.menu}<RowMenuTrigger spec={p.menu} />{/if}{#if p.ghost}{@const g = p.ghost}<button type="button" class="session-row-menu-trigger" data-ghost-menu aria-haspopup="menu" aria-label={t('leader.menu.label', { name: g.name })} data-tooltip="" tabindex="-1" onclick={(e) => { e.stopPropagation(); openGhostMenu(e.currentTarget, g); }}>{@html kebabSvg()}</button>{/if}</span></div>{#if p.meta}<div class="session-sidebar-row-meta">{#if p.meta.badge}<RowChip chip={p.meta.badge} />{/if}{#if p.meta.age}<RowChip chip={p.meta.age} />{/if}{#if p.meta.when}<RowChip chip={p.meta.when} />{/if}{#if p.meta.hint}<RowChip chip={p.meta.hint} />{/if}{#if p.meta.host}<RowChip chip={p.meta.host} />{/if}</div>{/if}{#if p.body}{#if p.body.mode === 'cozy'}<RowCozyBody body={p.body} actions={p.actions} />{:else}<RowDetailedBody body={p.body} actions={p.actions} />{/if}{/if}{#if p.context}<LimitGauge class="session-sidebar-row-context" variant="fill" pct={p.context.pct} scale={p.context.scale} meterText={p.context.label} height={1} />{/if}{#if armed}<RowWakeArm name={p.name.text} />{/if}</div>

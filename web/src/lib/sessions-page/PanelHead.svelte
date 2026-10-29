
<script lang="ts">
    import RowActionButton from './RowActionButton.svelte';
    import ProjectChip from './ProjectChip.svelte';
    import { runCplug } from '../item-menu/row-plugins';
    import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import KeepAwakeIcon from '../auto-sleep/KeepAwakeIcon.svelte';
    import SessionKebab from '../projects-shared/SessionKebab.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { SessionListItem, Translate } from '../sessions/types';
    import { agentsIconPlan, automationsIconPlan, shellsIconPlan, sharePlan, timersIconPlan, workflowIconPlan } from '../sidebar-shell/row-chips';
    import type { SidebarRow } from '../sidebar-shell/legacy';
    import { openSessionAutomationsFor } from '../sidebar-shell/row-controls';
    import type { PageRow } from './filters';
    import { isClosedRow, rowAction, type PanelAction } from './row-action';
    import { stateKeyOf } from './row-state';
    import { resumeWhyKey } from './resume-why';

    interface Props {
        row: PageRow;
        live: SessionListItem | undefined;
        asleepUnread?: boolean;
        pinned: boolean;
        keptAwake: boolean;
        t: Translate;
        onAct: (kind: PanelAction, row: PageRow) => void;
        onPin: (row: PageRow) => void;
        busy?: boolean;
    }
    const { row, live, asleepUnread = false, pinned, keptAwake, t, onAct, onPin, busy = false }: Props = $props();

    const s = $derived(row.s);
    const name = $derived(s.label ?? s.title);
    const mark = $derived(providerMark(row.provider));
    const asleep = $derived(s.state === 'asleep');
    const running = $derived(s.state === 'running');
    const action = $derived(rowAction(s));
    const closed = $derived(isClosedRow(s));
    const local = $derived(row.computer === null);
    const putBack = $derived(local && s.state === 'removed');
    const removable = $derived(local && s.state !== 'running' && s.state !== 'removed');
    const chipRow = $derived<SidebarRow>({ ...(live ?? {}), name: s.tmux_name ?? '', session_id: s.live_session_id, session_uuid: s.session_uuid });
    const share = $derived(live ? sharePlan(chipRow) : null);
    const markers = $derived(live ? [agentsIconPlan(chipRow), workflowIconPlan(chipRow), shellsIconPlan(chipRow), timersIconPlan(chipRow)].filter((m) => m !== null) : []);
    const automations = $derived(live ? automationsIconPlan(chipRow) : null);
    const pinLabel = $derived(pinned ? t('sessions.page.panel.unpin') : t('sessions.page.panel.pin'));

    async function openShare(): Promise<void> {
        await runCplug('share', { name: s.tmux_name ?? '', sessionId: s.live_session_id });
    }
</script>

<section class="sp-pn-sec" id="sp-pn-head">
    <div class="sp-pn-top">
        <div class="sp-pn-status">
            <SessionFace row={live ? { ...live, agent_family: row.provider } : { agent_family: row.provider }} lifecycle={live ? undefined : asleep ? 'asleep' : undefined} />
            <span data-pn-state>{t(`sessions.page.state.${stateKeyOf(s, live)}`)}</span>
            {#if live?.status_source}<span class="sp-pn-src">{t('sessions.page.panel.via', { source: live.status_source })}</span>{/if}
        </div>
        <div class="sp-pn-icons" role="toolbar" aria-label={t('sessions.page.panel.icons')}>
            {#if share}
                <IconButton variant="quiet" data-pic="share" label={share.attrs['aria-label'] ?? share.attrs.title ?? ''} onclick={() => void openShare()}>
                    {#snippet children()}{@html share!.svg}{/snippet}
                </IconButton>
            {/if}
            {#each markers as m (m.attrs.class)}
                <span class="sp-pic {m.attrs.class === 'session-sidebar-row-agents-icon' || m.attrs.class === 'session-sidebar-row-shells-icon' ? 'sp-pic-ok' : 'sp-pic-dim'}" role="img" title={m.attrs.title} aria-label={m.attrs['aria-label']}>{@html m.svg}</span>
            {/each}
            {#if automations}
                <button data-base-exempt="a status glyph that is also a key: a picture, not a labelled control" type="button" class="sp-pic {automations.attrs.class}" data-state={automations.attrs['data-state']} data-automations-session-uuid={automations.attrs['data-automations-session-uuid']} title={automations.attrs.title} aria-label={automations.attrs['aria-label']} onclick={(e) => openSessionAutomationsFor(e.currentTarget)}>{@html automations.svg}</button>
            {/if}
            {#if asleep}
                <span class="sp-pic sp-pic-dim" role="img" title={t('sessions.page.state.asleep')} aria-label={t('sessions.page.state.asleep')}>{@html glyphSvg('sleeping-agent', 13)}</span>
            {/if}
            {#if running && local && keptAwake}
                <span class="sp-pic sp-pic-cup"><KeepAwakeIcon sessionName={s.tmux_name} /></span>
            {/if}
            {#if s.tmux_name && !closed && local}
                <IconButton variant="quiet" data-pic="pin" pressed={pinned} label={pinLabel} onclick={() => onPin(row)}>
                    {#snippet children()}{@html glyphSvg('pin', 13)}{/snippet}
                </IconButton>
            {/if}
            <span class="sp-pic sp-pic-kebab"><SessionKebab session={s} {live} unread={asleepUnread} /></span>
        </div>
    </div>
    <h2 class="sp-pn-name">{name}</h2>
    <div class="sp-pn-meta">
        <span class="sp-pn-proj">
            <ProjectChip name={row.project} projectId={row.projectRef?.id ?? null} />{row.project}
        </span>
        {#if row.company}
            <span class="sp-pn-mi" data-meta="company"><span class="sp-pn-mic">{@html glyphSvg('building', 14)}</span><span>{row.company}</span></span>
        {/if}
        <span class="sp-pn-mi" data-meta="provider"><span class="sp-pn-mic" role="img" aria-label={mark.label}>{@html mark.svg}</span><span>{row.provider}</span></span>
        <span class="sp-pn-mi" data-meta="computer"><span class="sp-pn-mic"><Icon name="computer" size={14} /></span><span>{row.computer ?? t('sessions.page.filter.this_computer')}</span></span>
    </div>
    {#if action || putBack || removable}
        <div class="sp-pn-actions">
            {#if action}
                <RowActionButton {action} {name} {t} size="md" data-pn-act={action} disabled={busy} onclick={() => onAct(action, row)} />
            {/if}
            {#if putBack}
                <Button size="sm" data-pn-act="put-back" disabled={busy} onclick={() => onAct('put-back', row)}>{t('projects.page.action.put_back')}</Button>
            {/if}
            {#if removable}
                <Button size="sm" variant="danger" data-pn-act="remove" disabled={busy} onclick={() => onAct('remove', row)}>{t('projects.page.action.remove')}</Button>
            {/if}
        </div>
        {#if action === 'start'}<p class="sp-pn-note">{t('sessions.page.panel.start_note')}</p>{/if}
    {/if}
    {#if local}<p class="sp-pn-note" data-resume-why>{t(resumeWhyKey(s))}</p>{/if}
</section>

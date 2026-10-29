<script lang="ts">
  import Button from '../base/Button.svelte';
  import './control-center.css';
  import { sessions } from '../../opscenter/api';
  import Tabs, { type TabDef } from '../../opscenter/ui/Tabs.svelte';
  import { rowFor } from '../../opscenter/cells/terminal-viewer/meta';
  import { elapsed } from '../../opscenter/lib/format';
  import { t } from '../i18n/index.svelte';
  import { fetchSubagents, secondsSince, type SubagentRow } from '../subagents/subagents';
  import { emptyMessage, fetchTimers, type SessionTimers } from '../timers/timers';
  import { splitTimers, type TimerLine } from '../timers/timer-times';
  import {
    fetchBackgroundWork,
    processesEmpty,
    stopMessage,
    terminateProcess,
    type BackgroundProcess,
    type SessionBackgroundWork,
  } from '../background-work/background-work';
  import {
    batchMessage,
    interruptMessage,
    interruptSession,
    listedAgents,
    processesOf,
    refreshKey,
    terminateAll,
    revealInside,
    workCounts,
    CONTROL_SECTIONS,
    type ControlSection,
  } from './control-center';

  let {
    sessionId,
    focus = null,
    layout = 'columns',
  }: { sessionId: string; focus?: ControlSection | null; layout?: 'columns' | 'accordion' | 'tabs' | 'owner-list' } = $props();

  // svelte-ignore state_referenced_locally
  let openAccordion = $state<ControlSection>(focus ?? CONTROL_SECTIONS[0]!);
  function sectionOpen(section: ControlSection): boolean {
    return (layout !== 'accordion' && layout !== 'tabs') || openAccordion === section;
  }
  function headerVisible(section: ControlSection): boolean {
    return layout !== 'tabs' || openAccordion === section;
  }

  let ownerFilter = $state<'all' | 'agents' | 'shells' | 'timers'>('all');

  let timers = $state<SessionTimers | null>(null);
  let agentRows = $state<SubagentRow[] | null>(null);
  let work = $state<SessionBackgroundWork | null>(null);
  let failed = $state<Partial<Record<ControlSection, string>>>({});
  let notice = $state<Partial<Record<ControlSection, string>>>({});
  let armed = $state<string | null>(null);
  let busy = $state(false);
  let nowMs = $state(Date.now());
  let root = $state<HTMLElement | null>(null);

  const key = $derived(refreshKey(rowFor(sessions.data, sessionId) as Record<string, unknown> | null));
  const timerLines = $derived(splitTimers(timers?.timers ?? [], nowMs));
  const liveTimers = $derived(timerLines.live.length);
  let historyOpen = $state(false);
  const agents = $derived(agentRows ? listedAgents(agentRows, work) : null);
  const processes = $derived(work?.state === 'ok' ? work.processes : []);
  const counts = $derived(workCounts(agentRows, work));
  const sectionTabs = $derived<TabDef[]>(CONTROL_SECTIONS.map((section) => ({
    id: section,
    label: t(`control_center.section.${section}`),
    badge: section === 'timers' ? (timers ? liveTimers : null) : section === 'agents' ? counts.agents : counts.shells,
  })));
  const processesNote = $derived(work ? processesEmpty(work) : null);
  const unownedProcesses = $derived(
    processes.filter((p) => !p.agent_id || !(agents ?? []).some((a) => a.id === p.agent_id)),
  );

  let generation = 0;
  async function readAll(): Promise<void> {
    const mine = ++generation;
    const [tm, ag, bw] = await Promise.allSettled([
      fetchTimers(sessionId), fetchSubagents(sessionId), fetchBackgroundWork(sessionId),
    ]);
    if (mine !== generation) return;
    nowMs = Date.now();
    const why = (r: PromiseRejectedResult): string => (r.reason as Error)?.message ?? String(r.reason);
    const next: Partial<Record<ControlSection, string>> = {};
    if (tm.status === 'fulfilled') timers = tm.value;
    else next.timers = t('timers.list.failed', { reason: why(tm) });
    if (ag.status === 'fulfilled') agentRows = ag.value.subagents;
    else next.agents = t('subagents.list.failed', { reason: why(ag) });
    if (bw.status === 'fulfilled') work = bw.value;
    else next.processes = t('background_work.list.failed', { reason: why(bw) });
    failed = next;
  }

  $effect(() => {
    void key;
    void readAll();
  });
  $effect(() => () => { generation += 1; });

  /*  hidden  overflow: hidden */
  $effect(() => {
    const section = focus;
    if (!section) return;
    if (layout === 'accordion') { openAccordion = section; return; }
    if (!root) return;
    const el = root.querySelector<HTMLElement>(`[data-scc-section="${section}"]`);
    if (el) revealInside(root, el);
  });

  function age(iso: string | null): string {
    const seconds = secondsSince(iso, nowMs);
    return seconds === null ? t('opscenter.value.not_measured') : elapsed(seconds);
  }

  function arm(what: string, section: ControlSection): void {
    armed = what;
    notice = { ...notice, [section]: undefined };
  }

  async function act(section: ControlSection, run: () => Promise<string>): Promise<void> {
    busy = true;
    try {
      notice = { ...notice, [section]: await run() };
    } finally {
      busy = false;
      armed = null;
    }
    await readAll();
  }

  const stopOne = (row: BackgroundProcess) => act('processes', () =>
    terminateProcess(sessionId, row).then(stopMessage, stopMessage));
  const stopMany = (section: ControlSection, rows: BackgroundProcess[]) => act(section, () =>
    terminateAll(sessionId, rows).then(batchMessage, batchMessage));
  const interrupt = () => act('agents', () =>
    interruptSession(sessionId).then(interruptMessage, interruptMessage));

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || armed === null) return;
    event.preventDefault();
    event.stopPropagation();
    armed = null;
  }
</script>


{#snippet timerRow(line: TimerLine)}
  <li class="scc-row" data-scc-timer={line.live ? 'live' : 'ended'}>
    <span class="scc-type">{line.lead}</span>
    <span class="scc-text">{line.prompt}</span>
    <span class="scc-num" data-live={line.live ? 'true' : 'false'}>{line.when}</span>
  </li>
{/snippet}


{#snippet confirm(ask: string, yes: string, run: () => void)}
  <div class="scc-confirm" role="group">
    <span class="scc-ask">{ask}</span>
    <span class="scc-answers">
      <Button variant="danger" size="sm" disabled={busy} onclick={run}
        >{busy ? t('background_work.stop.stopping') : yes}</Button>
      <Button size="sm" disabled={busy}
        onclick={() => { armed = null; }}>{t('background_work.stop.cancel')}</Button>
    </span>
  </div>
{/snippet}

{#snippet head(section: ControlSection, count: number | null, action: string | null, what: string)}
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <header class="scc-head" data-scc-toggle={layout === 'accordion' ? 'true' : 'false'}
    role={layout === 'accordion' ? 'button' : undefined}
    tabindex={layout === 'accordion' ? 0 : undefined}
    aria-expanded={layout === 'accordion' ? (sectionOpen(section) ? 'true' : 'false') : undefined}
    onclick={() => { if (layout === 'accordion') openAccordion = section; }}
    onkeydown={(event) => {
      if (layout !== 'accordion' || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      openAccordion = section;
    }}>
    <h3 class="scc-label">{t(`control_center.section.${section}`)}</h3>
    {#if count !== null}<span class="scc-count">{count}</span>{/if}
    {#if action && armed !== what}
      <Button variant="danger" size="sm" data-scc-act disabled={busy}
        onclick={() => arm(what, section)}>{action}</Button>
    {/if}
  </header>
{/snippet}


{#snippet tabsRail()}
  <Tabs tabs={sectionTabs} active={openAccordion} onSelect={(id) => { openAccordion = id as ControlSection; }}
    label={t('control_center.label')} idBase="scc" class="scc-tabs" />
{/snippet}


{#snippet ownerList()}
  {@const chipCount = (kind: 'all' | 'agents' | 'shells' | 'timers') =>
    kind === 'all' ? (agents?.length ?? 0) + processes.length + liveTimers
      : kind === 'agents' ? (agents?.length ?? 0)
      : kind === 'shells' ? processes.length
      : liveTimers}
  <div class="scc-owner-toolbar">
    <div class="scc-chips" role="group" aria-label={t('control_center.owner.filter_label')}>
      {#each (['all', 'agents', 'shells', 'timers'] as const) as kind (kind)}
        <button type="button" class="scc-chip" data-active={ownerFilter === kind ? 'true' : 'false'}
          onclick={() => { ownerFilter = kind; }}>
          {t(`control_center.owner.chip.${kind}`)} <span class="scc-chip-count">{chipCount(kind)}</span>
        </button>
      {/each}
    </div>
    <div class="scc-owner-actions">
      {#if armed === 'all:agents'}
        {@render confirm(t('control_center.agents.all_ask'), t('control_center.agents.all_yes'), () => void interrupt())}
      {:else if agents && agents.some((a) => a.status === 'running')}
        <Button variant="danger" size="sm" data-scc-act disabled={busy} onclick={() => arm('all:agents', 'agents')}>{t('control_center.agents.all')}</Button>
      {/if}
      {#if armed === 'all:processes'}
        {@render confirm(t('control_center.processes.all_ask', { count: processes.length }), t('control_center.processes.all_yes'),
          () => void stopMany('processes', processes))}
      {:else if processes.length > 0}
        <Button variant="danger" size="sm" data-scc-act disabled={busy} onclick={() => arm('all:processes', 'processes')}>{t('control_center.processes.all')}</Button>
      {/if}
    </div>
  </div>
  {#if notice.agents}<p class="scc-note scc-notice" role="status">{notice.agents}</p>{/if}
  {#if notice.processes}<p class="scc-note scc-notice" role="status">{notice.processes}</p>{/if}
  <ul class="scc-owner-list" data-scc-section="agents">
    {#if ownerFilter === 'all' || ownerFilter === 'timers'}
      {#each timerLines.live as line (line.id)}
        <li class="scc-row" data-scc-kind="timers">
          <span class="scc-owner-kind">{t('control_center.owner.kind.timers')}</span>
          {@render timerRow(line)}
        </li>
      {/each}
    {/if}
    {#if ownerFilter === 'all' || ownerFilter === 'agents' || ownerFilter === 'shells'}
      {#each agents ?? [] as row (row.id)}
        {@const own = processesOf(work, row.id)}
        {#if ownerFilter !== 'shells'}
          <li class="scc-row" data-scc-kind="agents">
            <span class="scc-owner-kind">{t('control_center.owner.kind.agents')}</span>
            <span class="scc-type">{row.agent_type ?? t('subagents.list.type_unknown')}</span>
            <span class="scc-text">{row.description ?? t('subagents.list.no_description')}</span>
            <span class="scc-num">{row.status === 'running' ? age(row.started_at) : t('control_center.agents.finished')}</span>
            {#if own.length > 0 && armed !== `agent:${row.id}`}
              <Button variant="danger" size="sm" data-scc-stop disabled={busy}
                onclick={() => arm(`agent:${row.id}`, 'agents')}>{t('background_work.stop.arm')}</Button>
            {/if}
          </li>
          {#if armed === `agent:${row.id}`}
            {@render confirm(t('control_center.agents.stop_ask', { count: own.length }), t('background_work.stop.yes'),
              () => void stopMany('agents', own))}
          {/if}
        {/if}
        {#each own as p (p.pid)}
          <li class="scc-row scc-row--nested" data-scc-kind="shells">
            <span class="scc-owner-kind">{t('control_center.owner.kind.shells')}</span>
            <span class="scc-type">{p.task_id ?? t('background_work.process.shell')}</span>
            <span class="scc-text">{p.summary ?? t('background_work.process.no_summary')}</span>
            <span class="scc-num">{age(p.started_at)}</span>
            {#if armed !== `proc:${p.pid}`}
              <Button variant="danger" size="sm" data-scc-stop disabled={busy}
                onclick={() => arm(`proc:${p.pid}`, 'processes')}>{t('background_work.stop.arm')}</Button>
            {/if}
          </li>
          {#if armed === `proc:${p.pid}`}
            {@render confirm(t('background_work.stop.ask', { pid: String(p.pid), count: p.children }),
              t('background_work.stop.yes'), () => void stopOne(p))}
          {/if}
        {/each}
      {/each}
      {#if ownerFilter !== 'agents'}
        {#each unownedProcesses as p (p.pid)}
          <li class="scc-row" data-scc-kind="shells">
            <span class="scc-owner-kind">{t('control_center.owner.kind.shells')}</span>
            <span class="scc-type">{p.task_id ?? t('background_work.process.shell')}</span>
            <span class="scc-text">{p.summary ?? t('background_work.process.no_summary')}</span>
            <span class="scc-num">{age(p.started_at)}</span>
            {#if armed !== `proc:${p.pid}`}
              <Button variant="danger" size="sm" data-scc-stop disabled={busy}
                onclick={() => arm(`proc:${p.pid}`, 'processes')}>{t('background_work.stop.arm')}</Button>
            {/if}
          </li>
          {#if armed === `proc:${p.pid}`}
            {@render confirm(t('background_work.stop.ask', { pid: String(p.pid), count: p.children }),
              t('background_work.stop.yes'), () => void stopOne(p))}
          {/if}
        {/each}
      {/if}
    {/if}
    {#if (agents ?? []).length === 0 && unownedProcesses.length === 0 && timerLines.live.length === 0}
      <li class="scc-note" data-scc-empty="owner-list">{t('control_center.owner.empty')}</li>
    {/if}
  </ul>
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section class="scc" data-layout={layout} aria-label={t('control_center.label')} bind:this={root} onkeydown={onKeydown}>
{#if layout === 'owner-list'}
  {@render ownerList()}
{:else}
{#if layout === 'tabs'}{@render tabsRail()}{/if}
  <div class="scc-section" data-scc-section="timers" data-focused={focus === 'timers' ? 'true' : 'false'}
    data-open={sectionOpen('timers') ? 'true' : 'false'}>
    {#if headerVisible('timers')}{@render head('timers', timers ? liveTimers : null, null, '')}{/if}
    {#if sectionOpen('timers')}
    {#if failed.timers}
      <p class="scc-note" role="status">{failed.timers}</p>
    {:else if timers === null}
      <p class="scc-note" role="status">{t('timers.list.loading')}</p>
    {:else if emptyMessage(timers)}
      <p class="scc-note" data-scc-empty="timers">{emptyMessage(timers)}</p>
    {:else}
      
      {#if timerLines.live.length === 0}
        <p class="scc-note" data-scc-empty="timers-live">{t('control_center.timers.none_live')}</p>
      {:else}
        <ul class="scc-list">
          {#each timerLines.live as line (line.id)}
            {@render timerRow(line)}
          {/each}
        </ul>
      {/if}
      {#if timerLines.history.length > 0}
        <button type="button" class="scc-fold" aria-expanded={historyOpen ? 'true' : 'false'}
          onclick={() => { historyOpen = !historyOpen; }}
          >{t('control_center.timers.history', { count: timerLines.history.length })}</button>
        {#if historyOpen}
          <ul class="scc-list" data-scc-history="true">
            {#each timerLines.history as line (line.id)}
              {@render timerRow(line)}
            {/each}
          </ul>
        {/if}
      {/if}
    {/if}
    {/if}
  </div>

  <div class="scc-section" data-scc-section="agents" data-focused={focus === 'agents' ? 'true' : 'false'}
    data-open={sectionOpen('agents') ? 'true' : 'false'}>
    {#if headerVisible('agents')}{@render head('agents', counts.agents,
      agents && agents.some((a) => a.status === 'running') ? t('control_center.agents.all') : null, 'all:agents')}{/if}
    {#if sectionOpen('agents')}
    {#if armed === 'all:agents'}
      {@render confirm(t('control_center.agents.all_ask'), t('control_center.agents.all_yes'), () => void interrupt())}
    {/if}
    {#if notice.agents}<p class="scc-note scc-notice" role="status">{notice.agents}</p>{/if}
    {#if failed.agents}
      <p class="scc-note" role="status">{failed.agents}</p>
    {:else if agents === null}
      <p class="scc-note" role="status">{t('subagents.list.loading')}</p>
    {:else if agents.length === 0}
      <p class="scc-note" data-scc-empty="agents">{t('background_work.list.no_agents')}</p>
    {:else}
      <ul class="scc-list">
        {#each agents as row (row.id)}
          {@const own = processesOf(work, row.id)}
          <li class="scc-row" data-scc-agent={row.id}>
            <span class="scc-type">{row.agent_type ?? t('subagents.list.type_unknown')}</span>
            <span class="scc-text">{row.description ?? t('subagents.list.no_description')}</span>
            <span class="scc-num">{row.status === 'running' ? age(row.started_at) : t('control_center.agents.finished')}</span>
            {#if own.length > 0 && armed !== `agent:${row.id}`}
              <Button variant="danger" size="sm" data-scc-stop disabled={busy}
                onclick={() => arm(`agent:${row.id}`, 'agents')}>{t('background_work.stop.arm')}</Button>
            {:else if own.length === 0}
              <span class="scc-quiet">{t('control_center.agents.no_shells')}</span>
            {/if}
          </li>
          {#if armed === `agent:${row.id}`}
            {@render confirm(t('control_center.agents.stop_ask', { count: own.length }), t('background_work.stop.yes'),
              () => void stopMany('agents', own))}
          {/if}
        {/each}
      </ul>
    {/if}
    {/if}
  </div>

  <div class="scc-section" data-scc-section="processes" data-focused={focus === 'processes' ? 'true' : 'false'}
    data-open={sectionOpen('processes') ? 'true' : 'false'}>
    {#if headerVisible('processes')}{@render head('processes', counts.shells,
      processes.length > 0 ? t('control_center.processes.all') : null, 'all:processes')}{/if}
    {#if sectionOpen('processes')}
    {#if armed === 'all:processes'}
      {@render confirm(t('control_center.processes.all_ask', { count: processes.length }), t('control_center.processes.all_yes'),
        () => void stopMany('processes', processes))}
    {/if}
    {#if notice.processes}<p class="scc-note scc-notice" role="status">{notice.processes}</p>{/if}
    {#if failed.processes}
      <p class="scc-note" role="status">{failed.processes}</p>
    {:else if work === null}
      <p class="scc-note" role="status">{t('background_work.list.loading')}</p>
    {:else if processesNote}
      <p class="scc-note" data-scc-empty={work.state}>{processesNote}</p>
    {:else}
      <ul class="scc-list">
        {#each processes as row (row.pid)}
          <li class="scc-row" data-scc-pid={row.pid}>
            <span class="scc-type">{row.task_id ?? t('background_work.process.shell')}</span>
            <span class="scc-text">{row.summary ?? t('background_work.process.no_summary')}</span>
            <span class="scc-num">{age(row.started_at)}</span>
            {#if armed !== `proc:${row.pid}`}
              <Button variant="danger" size="sm" data-scc-stop disabled={busy}
                onclick={() => arm(`proc:${row.pid}`, 'processes')}>{t('background_work.stop.arm')}</Button>
            {/if}
            <span class="scc-meta">{t('background_work.process.meta', { pid: String(row.pid), count: row.children })}</span>
          </li>
          {#if armed === `proc:${row.pid}`}
            {@render confirm(t('background_work.stop.ask', { pid: String(row.pid), count: row.children }),
              t('background_work.stop.yes'), () => void stopOne(row))}
          {/if}
        {/each}
      </ul>
    {/if}
    {/if}
  </div>
{/if}
</section>

<script lang="ts">
  /* there is nothing */
  import { sessions } from '../../opscenter/api';
  import { rowFor } from '../../opscenter/cells/terminal-viewer/meta';
  import { t } from '../i18n/index.svelte';
  import { timerChip, untilText } from '../timers/timers';
  import { auth } from '../../opscenter/api/auth.svelte';
  import { fetchSubagents, type SubagentRow } from '../subagents/subagents';
  import { fetchBackgroundWork, type SessionBackgroundWork } from './background-work';
  import { refreshKey, workCounts, type ControlSection } from '../session-control/control-center';

  type Form = 'full' | 'short';

  let {
    sessionId,
    form = 'full',
    active = null,
    onwidths = undefined,
    onopen = undefined,
    hideAgents = false,
    hideShells = false,
    hideTimers = false,
  }: {
    sessionId: string;
    form?: Form;
    active?: ControlSection | null;
    onwidths?: (widths: Record<Form, number>) => void;
    onopen?: (section: ControlSection) => void;
    hideAgents?: boolean;
    hideShells?: boolean;
    hideTimers?: boolean;
  } = $props();

  const TICK_MS = 30000;

  const row = $derived(rowFor(sessions.data, sessionId));
  const wantsLists = $derived(!hideAgents || !hideShells);
  const key = $derived(refreshKey(row as Record<string, unknown> | null));
  let agentRows = $state<SubagentRow[] | null>(null);
  let work = $state<SessionBackgroundWork | null>(null);
  let generation = 0;
  $effect(() => {
    void key;
    if (!wantsLists || auth.state === 'signed-out') return;
    const mine = ++generation;
    void Promise.allSettled([fetchSubagents(sessionId), fetchBackgroundWork(sessionId)]).then(([ag, bw]) => {
      if (mine !== generation) return;
      agentRows = ag.status === 'fulfilled' ? ag.value.subagents : null;
      work = bw.status === 'fulfilled' ? bw.value : null;
    });
    return () => { generation += 1; };
  });
  const counts = $derived(workCounts(agentRows, work));
  const agentsCount = $derived(!hideAgents && counts.agents ? counts.agents : null);
  const shellsCount = $derived(!hideShells && counts.shells ? counts.shells : null);
  let nowMs = $state(Date.now());
  const timers = $derived(hideTimers ? null : timerChip(row, nowMs));
  const until = $derived(untilText(row?.timers_next_fire_at, nowMs));

  const ticking = $derived(timers !== null);
  $effect(() => {
    if (!ticking) return;
    const handle = setInterval(() => { nowMs = Date.now(); }, TICK_MS);
    return () => clearInterval(handle);
  });

  let fullCopy = $state<HTMLElement | null>(null);
  let shortCopy = $state<HTMLElement | null>(null);
  $effect(() => {
    const full = fullCopy;
    const short = shortCopy;
    const report = (): void => onwidths?.({ full: full?.offsetWidth ?? 0, short: short?.offsetWidth ?? 0 });
    report();
    if (!full || !short || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(report);
    observer.observe(full);
    observer.observe(short);
    return () => observer.disconnect();
  });

  function keepTerminalFocus(event: MouseEvent): void {
    event.preventDefault();
  }

  function ask(section: ControlSection, event: MouseEvent): void {
    event.stopPropagation();
    onopen?.(section);
  }
</script>


{#snippet agentsContent(f: Form)}
  <span class="oc-tfw-label">{t(f === 'full' ? 'background_work.foot.agents_label_full' : 'background_work.foot.agents_label')}</span><span class="oc-tfw-num">{agentsCount}</span>
{/snippet}

{#snippet shellsContent(f: Form)}
  <span class="oc-tfw-label">{t(f === 'full' ? 'background_work.foot.label_full' : 'background_work.foot.label')}</span><span class="oc-tfw-num">{shellsCount}</span>
{/snippet}

{#snippet timersContent(f: Form)}
  <svg class="oc-tfw-glyph" viewBox="0 0 10 10" aria-hidden="true" focusable="false"
    ><circle cx="5" cy="5" r="4" /><path d="M5 2.6V5l1.6 1" /></svg>
  {#if f === 'short' && until}
    <span class="oc-tfw-num">{t('timers.foot.short', { count: timers?.live ?? 0, time: until })}</span>
  {:else}
    
    {#if f === 'full'}<span class="oc-tfw-label">{t('timers.foot.label')}</span>{/if}
    <span class="oc-tfw-num">{timers?.live}</span>
    {#if until}<span class="oc-tfw-label">{t('timers.foot.next', { time: until })}</span>{/if}
  {/if}
{/snippet}

{#snippet copy(f: Form)}
  {#if agentsCount !== null}<span class="oc-tfw-seg">{@render agentsContent(f)}</span>{/if}
  {#if shellsCount !== null}<span class="oc-tfw-seg">{@render shellsContent(f)}</span>{/if}
  {#if timers !== null}<span class="oc-tfw-seg">{@render timersContent(f)}</span>{/if}
{/snippet}

{#if agentsCount !== null || shellsCount !== null || timers !== null}
  <span class="oc-tfw" data-form={form}>
    {#if agentsCount !== null}
      <button data-base-exempt="a segment of the terminal foot bar, drawn flush in the bar strip (foot-plan measures its exact width)" type="button" class="oc-tfw-seg" data-seg="agents"
        aria-expanded={active === 'agents' ? 'true' : 'false'} data-active={active === 'agents' ? 'true' : 'false'}
        aria-label={t('background_work.foot.agents_title', { count: agentsCount })}
        onmousedown={keepTerminalFocus} onclick={(e) => ask('agents', e)}
        >{@render agentsContent(form)}</button>
    {/if}
    {#if shellsCount !== null}
      <button data-base-exempt="a segment of the terminal foot bar, drawn flush in the bar strip (foot-plan measures its exact width)" type="button" class="oc-tfw-seg" data-seg="shells"
        aria-expanded={active === 'processes' ? 'true' : 'false'} data-active={active === 'processes' ? 'true' : 'false'}
        aria-label={t('background_work.foot.title', { count: shellsCount })}
        onmousedown={keepTerminalFocus} onclick={(e) => ask('processes', e)}
        >{@render shellsContent(form)}</button>
    {/if}
    {#if timers !== null}
      <button data-base-exempt="a segment of the terminal foot bar, drawn flush in the bar strip (foot-plan measures its exact width)" type="button" class="oc-tfw-seg" data-seg="timers"
        aria-expanded={active === 'timers' ? 'true' : 'false'} data-active={active === 'timers' ? 'true' : 'false'} aria-label={timers.title}
        onmousedown={keepTerminalFocus} onclick={(e) => ask('timers', e)}
        >{@render timersContent(form)}</button>
    {/if}
    <span class="oc-tfw oc-tfw-measure" aria-hidden="true" bind:this={fullCopy}>{@render copy('full')}</span>
    <span class="oc-tfw oc-tfw-measure" aria-hidden="true" bind:this={shortCopy}>{@render copy('short')}</span>
  </span>
{/if}

<style>
  .oc-tfw {
    position: relative;
    display: flex;
    flex: 0 0 auto;
    align-items: stretch;
    background: var(--oc-ground-titlerow);
    border-top: 1px solid var(--oc-line-rule);
    box-shadow: inset 1px 0 0 0 var(--oc-line-rule);
    font-size: var(--oc-fs-label);
    color: var(--oc-text-secondary);
  }

  .oc-tfw-measure {
    position: absolute;
    right: 0;
    bottom: 0;
    visibility: hidden;
    pointer-events: none;
    white-space: nowrap;
  }

  .oc-tfw-seg {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin: 0;
    padding: 0 10px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    white-space: nowrap;
    cursor: pointer;
    appearance: none;
  }

  .oc-tfw-seg + .oc-tfw-seg {
    box-shadow: inset 1px 0 0 0 var(--oc-line-rule);
  }

  .oc-tfw-seg:hover,
  .oc-tfw-seg[data-active='true'] {
    background: var(--oc-ground-hover);
    color: var(--oc-text-primary);
  }

  .oc-tfw-label {
    color: var(--oc-text-dim);
  }

  .oc-tfw-seg[data-seg='agents'] .oc-tfw-num,
  .oc-tfw-seg[data-seg='shells'] .oc-tfw-num {
    color: var(--oc-green-bright);
  }

  .oc-tfw-num {
    color: var(--oc-text-secondary);
    font-variant-numeric: tabular-nums;
  }

  .oc-tfw-glyph {
    width: 10px;
    height: 10px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.2;
    stroke-linecap: round;
    color: var(--oc-text-dim);
  }
</style>

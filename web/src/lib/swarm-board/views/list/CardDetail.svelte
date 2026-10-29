
<script lang="ts">
  import { t } from '../../../i18n/index.svelte';
  import { authFetch } from '../../../../opscenter/api/auth.svelte';
  import AgentFace from '../../AgentFace.svelte';
  import TaskMark from '../../../../opscenter/ui/TaskMark.svelte';
  import StatusGlyph from '../../StatusGlyph.svelte';
  import type { BoardData } from '../../board-data.svelte';
  import type { CardView } from '../../board-types';
  import CardVerdict from './CardVerdict.svelte';
  import { historyLines, phases, stamp, type CardEvent, type Who } from './list-model';

  interface Props {
    card: CardView;
    companyName: string | null;
    laneName: string;
    data: BoardData;
  }
  let { card, companyName, laneName, data }: Props = $props();

  let events = $state<CardEvent[]>([]);
  let history = $state<'loading' | 'ok' | 'error'>('loading');
  let historyError = $state('');
  let asked = '';

  $effect(() => {
    const key = `${card.id}:${card.revision}:${card.updated_at}`;
    if (key === asked) return;
    asked = key;
    authFetch<{ card_id: number; events: CardEvent[] }>(`/swarm/cards/${card.id}/events`).then(
      (answer) => {
        if (asked !== key) return;
        events = answer.events;
        history = 'ok';
      },
      (failure) => {
        if (asked !== key) return;
        history = 'error';
        historyError = failure instanceof Error ? failure.message : String(failure);
      },
    );
  });

  const holder = $derived(card.holder ? (data.agent(card.holder.agent_id) ?? null) : null);
  const strip = $derived(phases(card, events));
  const lines = $derived(historyLines(events));
  const progress = $derived(card.column === 'in_progress' && typeof card.progress === 'number' ? Math.max(0, Math.min(100, Math.round(card.progress))) : null);

  function named(who: Who): string {
    if (who.kind === 'you') return t('swarm.board.list.who.you');
    if (who.kind === 'agent') return data.agent(who.id)?.display_name ?? t('swarm.board.list.who.agent', { id: who.id });
    return who.name;
  }
</script>

<div class="sbd" data-swarm-list-detail={card.id}>
  <div class="sbd-head">
    <StatusGlyph column={card.column} label={t(`swarm.board.col.${card.column}`)} />
    <span>#{card.id}</span>
    {#if companyName}<span class="sbd-pill" data-swarm-list-company>{companyName}</span>{/if}
    <span class="sbd-pill">{laneName}</span>
    <span class="sbd-gap"></span>
    {#if card.holder}
      <span class="sbd-holder">
        <AgentFace agent={holder ?? { id: card.holder.agent_id, display_name: card.holder.name ?? `#${card.holder.agent_id}`, rank: 'task', state: 'asleep', thread_key: '' }}
                   working={card.column === 'in_progress'} colors={data.colors} looks={data.looks} />
        <span class="sbd-holder-name"><TaskMark rank={holder?.rank} />{holder?.display_name ?? card.holder.name ?? t('swarm.board.list.who.agent', { id: card.holder.agent_id })}</span>
      </span>
    {/if}
  </div>
  <h2 class="sbd-title">{card.title}</h2>
  {#if card.summary && card.summary.trim() !== card.title.trim()}<p class="sbd-summary" data-swarm-detail-summary>{card.summary}</p>{/if}

  <ol class="sbd-phases" data-swarm-list-phases>
    {#each strip as step (step.phase)}
      <li class="sbd-phase" class:sbd-phase--on={step.reached} data-phase={step.phase} data-reached={step.reached ? 'true' : 'false'}>
        <div class="sbd-phase-mark">
          {#if step.reached}
            <StatusGlyph column={step.column} size={16} />
          {:else}
            <svg class="sbd-phase-ghost" width="16" height="16" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" /></svg>
          {/if}
          <span class="sbd-phase-line"></span>
        </div>
        <div class="sbd-phase-name">{t(`swarm.board.list.phase.${step.phase}`)}</div>
        <div class="sbd-phase-at">{step.reached ? (step.at === null ? t('swarm.board.list.phase.unrecorded') : stamp(step.at)) : t('swarm.board.list.phase.not_yet')}</div>
      </li>
    {/each}
  </ol>

  {#if card.column === 'in_progress'}
    <div class="sbd-label">{t('swarm.board.list.progress')}</div>
    {#if progress === null}
      <p class="sbd-quiet">{t('swarm.board.list.progress.none')}</p>
    {:else}
      <div class="sbd-progress" role="img" aria-label={t('swarm.board.progress', { pct: progress })}>
        <span class="sbd-track"><span class="sbd-bar" style:width="{progress}%"></span></span>
        <span class="sbd-pct">{t('swarm.board.progress', { pct: progress })}</span>
      </div>
    {/if}
  {/if}

  <div class="sbd-label">{t('swarm.board.list.result')}</div>
  <p class="sbd-text" class:sbd-quiet={!card.result}>{card.result || t('swarm.board.list.result.none')}</p>

  <div class="sbd-label">{t('swarm.board.list.validation')}</div>
  <div class="sbd-box">
    {#if !card.how_to_validate && !card.proof}
      <p class="sbd-quiet">{t('swarm.board.list.validation.none')}</p>
    {/if}
    {#if card.how_to_validate}
      <div class="sbd-sub">{t('swarm.board.list.validation.steps')}</div>
      <p class="sbd-text">{card.how_to_validate}</p>
    {/if}
    {#if card.proof}
      <div class="sbd-sub">{t('swarm.board.list.validation.proof')}</div>
      <p class="sbd-text">{card.proof}</p>
    {/if}
  </div>

  <div class="sbd-label">{t('swarm.board.list.history')}</div>
  {#if history === 'error'}
    <p class="sbd-quiet sbd-bad">{t('swarm.board.list.history.error', { error: historyError })}</p>
  {:else if history === 'loading' && lines.length === 0}
    <p class="sbd-quiet">{t('swarm.board.list.history.loading')}</p>
  {:else if lines.length === 0}
    <p class="sbd-quiet">{t('swarm.board.list.history.none')}</p>
  {:else}
    <ul class="sbd-history" data-swarm-list-history>
      {#each lines as line, i (i)}
        <li class="sbd-event" data-swarm-list-event>
          <StatusGlyph column={line.column} size={12} label={t(`swarm.board.col.${line.column}`)} />
          <span class="sbd-event-text">{t(line.key, { who: named(line.who), column: t(`swarm.board.col.${line.column}`) })}{#if line.detail && (line.key === 'swarm.board.list.event.sent_back' || line.key === 'swarm.board.list.event.noted')}: {line.detail}{/if}</span>
          <span class="sbd-event-at">{stamp(line.at)}</span>
        </li>
      {/each}
    </ul>
  {/if}

  <CardVerdict {card} {data} />
</div>

<style>
  @layer components {
    .sbd {
      min-width: 0;
      padding: 28px 36px;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
      line-height: 1.5;
    }
    .sbd-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbd-pill {
      padding: 1px 7px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.06em;
      white-space: nowrap;
    }
    .sbd-gap {
      flex: 1;
    }
    .sbd-holder {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      color: var(--oc-text-secondary);
    }
    .sbd-holder-name {
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbd-title {
      margin: 14px 0 0;
      color: var(--oc-text-bright);
      font-size: 17px;
      font-weight: 600;
      line-height: 1.4;
      word-break: break-word;
    }
    .sbd-summary {
      margin: 8px 0 0;
      color: var(--oc-text-secondary);
      line-height: 1.6;
      word-break: break-word;
    }
    .sbd-phases {
      display: flex;
      gap: 10px;
      margin: 26px 0 0;
      padding: 16px 0 4px;
      list-style: none;
      box-shadow: 0 -1px 0 var(--oc-line-rule), 0 1px 0 var(--oc-line-rule);
    }
    .sbd-phase {
      flex: 1;
      min-width: 0;
    }
    .sbd-phase-mark {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .sbd-phase-line {
      flex: 1;
      height: 1px;
      background: var(--oc-line-rule);
    }
    .sbd-phase--on .sbd-phase-line {
      background: var(--oc-text-muted);
    }
    .sbd-phase-ghost {
      flex: none;
      fill: none;
      stroke: var(--oc-line-rule);
      stroke-width: 1.5;
      stroke-dasharray: 2 2;
    }
    .sbd-phase-name {
      margin-top: 8px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbd-phase--on .sbd-phase-name {
      color: var(--oc-text-bright);
    }
    .sbd-phase-at {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbd-label {
      margin: 26px 0 10px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbd-progress {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .sbd-track {
      position: relative;
      flex: 1;
      height: 4px;
      border-radius: 2px;
      background: var(--oc-line-rule);
    }
    .sbd-bar {
      display: block;
      height: 4px;
      border-radius: 2px;
      background: var(--oc-green);
    }
    .sbd-pct {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-body);
    }
    .sbd-text {
      margin: 0;
      color: var(--oc-text-primary);
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .sbd-quiet {
      margin: 0;
      color: var(--oc-text-muted);
      line-height: 1.65;
    }
    .sbd-bad {
      color: var(--oc-coral);
    }
    .sbd-box {
      padding: 12px 14px;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-card);
    }
    .sbd-sub {
      margin: 0 0 4px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .sbd-sub:not(:first-child) {
      margin-top: 12px;
    }
    .sbd-history {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .sbd-event {
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 30px;
    }
    .sbd-event-text {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-secondary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sbd-event-at {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    @container swarm-list (max-width: 720px) {
      .sbd {
        padding: 20px 16px;
      }
    }
  }
</style>

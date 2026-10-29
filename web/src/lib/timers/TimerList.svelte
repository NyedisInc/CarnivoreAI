<script lang="ts">
  import { onMount } from 'svelte';
  import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
  import '../subagents/popup-list.css';
  import { t } from '../i18n/index.svelte';
  import type { Placement } from '../drawer-tabs/add-component-menu';
  import { placeUnderAnchor } from '../dialog-frame/popup-placement';
  import {
    emptyMessage,
    fetchTimers,
    orderRows,
    scheduleText,
    untilText,
    type SessionTimers,
    type TimerRow,
  } from './timers';

  let {
    anchor,
    sessionId,
    name,
    onClose,
  }: {
    anchor: HTMLElement | null;
    sessionId: string;
    name: string;
    onClose: () => void;
  } = $props();

  let payload = $state<SessionTimers | null>(null);
  let failure = $state<string | null>(null);
  let panel = $state<HTMLElement | null>(null);
  let place = $state<Placement | null>(null);
  const nowMs = Date.now();

  const rows = $derived(payload ? orderRows(payload.timers) : []);
  const empty = $derived(payload ? emptyMessage(payload) : null);

  onMount(() => {
    let live = true;
    fetchTimers(sessionId)
      .then((body) => {
        if (live) payload = body;
      })
      .catch((err: unknown) => {
        if (live) failure = t('timers.list.failed', { reason: (err as Error).message });
      });
    return () => {
      live = false;
    };
  });

  function measure(): void {
    const next = placeUnderAnchor(anchor, panel);
    if (next) place = next;
  }

  $effect(() => {
    void rows.length;
    void failure;
    void empty;
    measure();
  });

  function close(): void {
    onClose();
    anchor?.focus();
  }

  function tone(row: TimerRow): string {
    if (row.status === 'live') return 'sal-status--live';
    if (row.status === 'unknown' || row.status === 'shape_unrecognized') return 'sal-status--unknown';
    return 'sal-status--ended';
  }

  function fires(row: TimerRow): string {
    if (row.status !== 'live') return '';
    return untilText(row.fire_at, nowMs) ?? t('timers.list.no_fire_time');
  }
</script>


<AnchoredPopup
  class="sal-panel"
  label={t('timers.list.label', { name })}
  tabindex={-1}
  data-timer-list=""
  bind:element={panel}
  {anchor}
  placement="manual"
  style={place
    ? `left: ${Math.round(place.left)}px; top: ${Math.round(place.top)}px; max-height: ${Math.round(place.maxHeight)}px`
    : 'left: 0; top: 0; opacity: 0'}
  onPlace={measure}
  initialFocus="self"
  escape="window"
  {onClose}
  onEscape={close}
>
  <header class="sal-titlebar">
    <h2 class="sal-title">{t('timers.list.title')}</h2>
    <span class="sal-name">{name}</span>
    <button type="button" class="sal-close" onclick={close}>{t('timers.list.close')}</button>
  </header>

  {#if failure}
    <p class="sal-note" role="status">{failure}</p>
  {:else if payload === null}
    <p class="sal-note" role="status">{t('timers.list.loading')}</p>
  {:else}
    {#if payload.counts}
      <p class="sal-summary">
        {t('timers.list.summary', {
          live: payload.counts.live,
          ended: payload.counts.total - payload.counts.live - payload.counts.unknown,
          unknown: payload.counts.unknown,
        })}
      </p>
    {/if}
    {#if empty}
      <p class="sal-note" data-timers-empty={payload.state}>{empty}</p>
    {:else}
      <table class="sal-table sal-table--timers">
        <thead>
          <tr>
            <th scope="col">{t('timers.list.col.status')}</th>
            <th scope="col">{t('timers.list.col.schedule')}</th>
            <th scope="col" class="sal-num">{t('timers.list.col.fires')}</th>
            <th scope="col">{t('timers.list.col.prompt')}</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row (row.id)}
            <tr data-timer-status={row.status}>
              <td><span class="sal-status {tone(row)}">{t(`timers.status.${row.status}`)}</span></td>
              <td class="sal-type">{scheduleText(row)}</td>
              <td class="sal-num">{fires(row)}</td>
              <td>{row.prompt ?? t('timers.list.no_prompt')}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if payload.background}
      <p class="sal-note" data-timers-background>
        {payload.background.open === null
          ? t('timers.list.background_unmeasured')
          : t('timers.list.background', { count: payload.background.open })}
      </p>
      <!-- Daily Bulletin -->
      {#each payload.background.parked as entry (entry.task_id)}
        <p class="sal-note" data-timers-parked data-timers-parked-live={entry.live}>{entry.summary}</p>
      {/each}
    {/if}
  {/if}
</AnchoredPopup>

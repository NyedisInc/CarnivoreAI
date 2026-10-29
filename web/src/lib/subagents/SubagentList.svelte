<script lang="ts">
  import { onMount } from 'svelte';
  import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
  import './popup-list.css';
  import { Button } from '../base';
  import { t } from '../i18n/index.svelte';
  import { elapsed } from '../../opscenter/lib/format';
  import type { Placement } from '../drawer-tabs/add-component-menu';
  import { placeUnderAnchor } from '../dialog-frame/popup-placement';
  import {
    emptyMessage,
    fetchSubagents,
    orderRows,
    secondsSince,
    type SessionSubagents,
  } from './subagents';

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

  let payload = $state<SessionSubagents | null>(null);
  let failure = $state<string | null>(null);
  let panel = $state<HTMLElement | null>(null);
  let place = $state<Placement | null>(null);
  const nowMs = Date.now();

  const rows = $derived(payload ? orderRows(payload.subagents) : []);
  const empty = $derived(payload ? emptyMessage(payload) : null);
  const hidden = $derived(
    payload?.counts ? Math.max(0, payload.counts.total - payload.counts.listed) : 0,
  );

  onMount(() => {
    let live = true;
    fetchSubagents(sessionId)
      .then((body) => {
        if (live) payload = body;
      })
      .catch((err: unknown) => {
        if (live) failure = t('subagents.list.failed', { reason: (err as Error).message });
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

  function age(iso: string | null): string {
    const seconds = secondsSince(iso, nowMs);
    return seconds === null ? t('opscenter.value.not_measured') : elapsed(seconds);
  }
</script>


<AnchoredPopup
  class="sal-panel"
  label={t('subagents.list.label', { name })}
  tabindex={-1}
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
    <h2 class="sal-title">{t('subagents.list.title')}</h2>
    <span class="sal-name">{name}</span>
    <Button size="sm" onclick={close}>{t('subagents.list.close')}</Button>
  </header>

  {#if failure}
    <p class="sal-note" role="status">{failure}</p>
  {:else if payload === null}
    <p class="sal-note" role="status">{t('subagents.list.loading')}</p>
  {:else}
    {#if payload.counts}
      <p class="sal-summary">
        {t('subagents.list.summary', {
          running: payload.counts.running,
          done: payload.counts.done,
          unknown: payload.counts.unknown,
        })}
      </p>
    {/if}
    {#if empty}
      <p class="sal-note" data-subagents-empty={payload.state}>{empty}</p>
    {:else}
      <table class="sal-table sal-table--subagents">
        <thead>
          <tr>
            <th scope="col">{t('subagents.list.col.status')}</th>
            <th scope="col">{t('subagents.list.col.type')}</th>
            <th scope="col">{t('subagents.list.col.description')}</th>
            <th scope="col" class="sal-num">{t('subagents.list.col.age')}</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row (row.id)}
            <tr data-subagent-status={row.status}>
              <td><span class="sal-status sal-status--{row.status}">{t(`subagents.status.${row.status}`)}</span></td>
              <td class="sal-type">{row.agent_type ?? t('subagents.list.type_unknown')}</td>
              <td>{row.description ?? t('subagents.list.no_description')}</td>
              <td class="sal-num">{age(row.started_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if hidden > 0}
        <p class="sal-note">{t('subagents.list.more', { count: hidden })}</p>
      {/if}
    {/if}
  {/if}
</AnchoredPopup>

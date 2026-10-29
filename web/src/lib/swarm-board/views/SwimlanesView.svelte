
<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { COLUMNS, type CardView } from '../board-types';
  import CardPane from '../CardPane.svelte';
  import CardNotice from '../CardNotice.svelte';
  import { findCard } from './list/list-model';
  import StatusGlyph from '../StatusGlyph.svelte';
  import SwimLane from './swimlanes/SwimLane.svelte';
  import { isFolded, orderLanes, readChatColumn, readFolds, writeChatColumn, writeFolds } from './swimlanes/lane-model';
  import type { BoardViewProps } from '../view-props';

  let { data }: BoardViewProps = $props();

  let folds = $state(readFolds());
  let chat = $state(readChatColumn());
  let openId = $state<number | null>(null);
  let root = $state<HTMLElement | null>(null);
  let pane = $state<HTMLElement | null>(null);
  const open = $derived(findCard(data.lanes, openId));
  const lanes = $derived(orderLanes(data.lanes));
  const totals = $derived(Object.fromEntries(COLUMNS.map((c) => [c, data.lanes.reduce((n, lane) => n + lane.counts[c], 0)])) as Record<(typeof COLUMNS)[number], number>);

  /* the detail pane */
  async function openCard(card: CardView): Promise<void> {
    openId = openId === card.id ? null : card.id;
    await tick();
    if (openId !== null && root && root.clientWidth <= 720) pane?.scrollIntoView({ block: 'start' });
  }

  function flipChat(): void {
    chat = !chat;
    writeChatColumn(chat);
  }

  function toggle(key: string, folded: boolean): void {
    folds = { ...folds, [key]: !folded };
    writeFolds(folds);
  }
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && openId !== null) openId = null; }} />

<div class="sbs" class:sbs--open={open !== null} data-swarm-view="swimlanes" bind:this={root}>
  <div class="sbs-main">
    <div class="sbs-cols" class:sbs-cols--chat={chat} data-swarm-columns>
      <div class="sbs-tools">
        <button type="button" class="sbs-key" aria-pressed={chat} data-swarm-chat-toggle onclick={flipChat}>{t('swarm.board.chat.toggle')}</button>
      </div>
      {#if chat}
        <div class="sbs-col sbs-col--chat" data-swarm-col="chat"><span class="sbs-col-name">{t('swarm.board.chat.col')}</span></div>
      {/if}
      {#each COLUMNS as column (column)}
        <div class="sbs-col">
          <StatusGlyph {column} />
          <span class="sbs-col-name">{t(`swarm.board.col.${column}`)}</span>
          <span class="sbs-col-n">{totals[column]}</span>
        </div>
      {/each}
      <CardNotice />
    </div>
    {#if lanes.length === 0 && data.status === 'ok'}
      <p class="sbs-empty" data-swarm-board-empty>{data.search ? t('swarm.board.no_match', { q: data.search }) : t('swarm.board.empty')}</p>
    {/if}
    {#each lanes as lane (lane.list_key)}
      {@const folded = isFolded(lane, folds, data.archived === 'only')}
      <SwimLane {lane} {data} {folded} onToggle={() => toggle(lane.list_key, folded)} onOpen={(card) => void openCard(card)} openId={open?.card.id ?? null} {chat} />
    {/each}
  </div>
  {#if open}
    <CardPane found={open} {data} view="swimlanes" onClose={() => (openId = null)} bind:el={pane} />
  {/if}
</div>

<style>
  @layer components {
    /* the detail pane */
    .sbs {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      align-items: start;
      min-width: 0;
      font-family: var(--font-mono);
    }
    .sbs--open {
      grid-template-columns: minmax(0, 60fr) minmax(0, 40fr);
    }
    .sbs-main {
      container: swarm-board / inline-size;
      min-width: 0;
      padding-bottom: var(--oc-space-5);
    }
    @container swarm-board-shell (max-width: 720px) {
      .sbs--open {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    .sbs-cols {
      position: sticky;
      top: 0;
      z-index: 2;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 12px 0 14px;
      background: var(--oc-ground-page);
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbs-cols--chat {
      grid-template-columns: minmax(0, 1.5fr) repeat(4, minmax(0, 1fr));
    }
    .sbs-tools {
      display: flex;
      grid-column: 1 / -1;
      justify-content: flex-end;
    }
    .sbs-key {
      --_bd: var(--oc-line-rule);
      padding: 4px 11px;
      border: 1px solid var(--_bd);
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      white-space: nowrap;
      cursor: pointer;
    }
    .sbs-key:hover {
      color: var(--oc-text-bright);
    }
    .sbs-key[aria-pressed='true'] {
      --_bd: var(--oc-cyan);
      background: color-mix(in srgb, var(--oc-cyan) 12%, transparent);
      color: var(--oc-cyan);
    }
    .sbs-col {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 0 10px;
    }
    .sbs-col-name {
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .sbs-col-n {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    @container swarm-board (max-width: 720px) {
      .sbs-cols, .sbs-cols--chat {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px 16px;
      }
      .sbs-col--chat {
        display: none;
      }
    }
    .sbs-empty {
      margin: 20px 0 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
  }
</style>

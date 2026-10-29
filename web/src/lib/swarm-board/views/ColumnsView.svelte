
<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import type { CardView } from '../board-types';
  import CardPane from '../CardPane.svelte';
  import CardNotice from '../CardNotice.svelte';
  import { findCard } from './list/list-model';
  import { orderLanes } from './swimlanes/lane-model';
  import ProjectColumn from './columns/ProjectColumn.svelte';
  import type { BoardViewProps } from '../view-props';

  let { data }: BoardViewProps = $props();

  let openId = $state<number | null>(null);
  let root = $state<HTMLElement | null>(null);
  let pane = $state<HTMLElement | null>(null);
  const open = $derived(findCard(data.lanes, openId));
  const lanes = $derived(orderLanes(data.lanes));

  /* the detail pane */
  async function openCard(card: CardView): Promise<void> {
    openId = openId === card.id ? null : card.id;
    await tick();
    if (openId !== null && root && root.clientWidth <= 720) pane?.scrollIntoView({ block: 'start' });
  }
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && openId !== null) openId = null; }} />

<div class="sbj" class:sbj--open={open !== null} data-swarm-view="columns" bind:this={root}>
  <div class="sbj-main">
    <CardNotice />
    {#if lanes.length === 0 && data.status === 'ok'}
      <p class="sbj-empty" data-swarm-board-empty>{data.search ? t('swarm.board.no_match', { q: data.search }) : t('swarm.board.empty')}</p>
    {/if}
    <div class="sbj-strip" data-swarm-columns-strip>
      {#each lanes as lane (lane.list_key)}
        <ProjectColumn {lane} {data} onOpen={(card) => void openCard(card)} openId={open?.card.id ?? null} />
      {/each}
    </div>
  </div>
  {#if open}
    <CardPane found={open} {data} view="columns" onClose={() => (openId = null)} bind:el={pane} />
  {/if}
</div>

<style>
  @layer components {
    /* the detail pane */
    .sbj {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      align-items: start;
      min-width: 0;
      font-family: var(--font-mono);
    }
    .sbj--open {
      grid-template-columns: minmax(0, 60fr) minmax(0, 40fr);
    }
    .sbj-main {
      container: swarm-columns / inline-size;
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-width: 0;
      padding: 20px 0 var(--oc-space-5);
    }
    .sbj-strip {
      display: flex;
      align-items: flex-start;
      gap: 20px;
      min-width: 0;
      padding-bottom: 6px;
      overflow-x: auto;
    }
    .sbj-empty {
      margin: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    @container swarm-columns (max-width: 720px) {
      .sbj-strip {
        flex-direction: column;
        align-items: stretch;
        gap: 28px;
        overflow-x: visible;
      }
    }
    @container swarm-board-shell (max-width: 720px) {
      .sbj--open {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  }
</style>

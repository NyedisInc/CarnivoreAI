
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
    import StatusGlyph from '../StatusGlyph.svelte';
  import ListRow from './list/ListRow.svelte';
  import CardDetail from './list/CardDetail.svelte';
  import { findCard, listBands } from './list/list-model';
  import type { BoardViewProps } from '../view-props';

  let { data }: BoardViewProps = $props();

  let picked = $state<number | null>(null);
  const bands = $derived(listBands(data.lanes));
  const firstId = $derived(bands[0]?.rows[0]?.card.id ?? null);
  const open = $derived(findCard(data.lanes, picked) ?? findCard(data.lanes, firstId));
</script>

<div class="sbli" data-swarm-view="list">
  <div class="sbli-grid">
    <div class="sbli-list" data-swarm-list>
      {#if bands.length === 0 && data.status === 'ok'}
        <p class="sbli-empty" data-swarm-board-empty>{data.search ? t('swarm.board.no_match', { q: data.search }) : t('swarm.board.list.empty')}</p>
      {/if}
      {#each bands as band (band.band)}
        <div class="sbli-band" class:sbli-band--you={band.band === 'review'} data-swarm-list-band={band.band}>
          <StatusGlyph column={band.band} />
          <span class="sbli-band-name">{band.band === 'review' ? t('swarm.board.list.needs_you') : t(`swarm.board.col.${band.band}`)}</span>
          <span class="sbli-band-n">{band.band === 'review' ? t('swarm.board.list.needs_you_count', { count: band.rows.length }) : band.rows.length}</span>
        </div>
        {#each band.rows as row (row.card.id)}
          <ListRow {row} {data} selected={open?.card.id === row.card.id} onPick={() => (picked = row.card.id)} />
        {/each}
      {/each}
    </div>
    <aside class="sbli-pane" aria-label={t('swarm.board.list.detail')}>
      {#if open}
        {#key open.card.id}
          <CardDetail card={open.card} laneName={open.laneName} companyName={open.companyName} {data} />
        {/key}
      {:else if bands.length > 0}
        <p class="sbli-empty sbli-pick">{t('swarm.board.list.pick')}</p>
      {/if}
    </aside>
  </div>
</div>

<style>
  @layer components {
    /* the detail pane */
    .sbli {
      container: swarm-list / inline-size;
      min-width: 0;
    }
    .sbli-grid {
      display: grid;
      grid-template-columns: minmax(0, 45fr) minmax(0, 55fr);
      align-items: start;
      min-width: 0;
      font-family: var(--font-mono);
    }
    .sbli-list {
      min-width: 0;
      padding-bottom: var(--oc-space-5);
      box-shadow: 1px 0 0 var(--oc-line-rule);
    }
    .sbli-pane {
      position: sticky;
      top: 0;
      min-width: 0;
      max-height: 100dvh;
      overflow: auto;
    }
    .sbli-band {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 34px;
      padding: 0 20px;
      background: var(--oc-ground-card);
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }
    .sbli-band--you {
      height: 38px;
      gap: 10px;
      background: color-mix(in srgb, var(--oc-cyan) 10%, transparent);
      box-shadow: inset 2px 0 0 var(--oc-cyan), 0 1px 0 var(--oc-line-rule);
    }
    .sbli-band-name {
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .sbli-band--you .sbli-band-name {
      color: var(--oc-cyan);
    }
    .sbli-band-n {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbli-band--you .sbli-band-n {
      color: var(--oc-text-secondary);
    }
    .sbli-empty {
      margin: 20px;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
    .sbli-pick {
      margin: 28px 36px;
    }
    @container swarm-list (max-width: 720px) {
      .sbli-grid {
        grid-template-columns: minmax(0, 1fr);
      }
      .sbli-list {
        box-shadow: 0 1px 0 var(--oc-line-rule);
      }
      .sbli-pane {
        position: static;
        max-height: none;
      }
    }
  }
</style>

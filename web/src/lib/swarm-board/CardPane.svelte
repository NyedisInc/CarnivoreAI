
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import CardDetail from './views/list/CardDetail.svelte';
  import type { FoundCard } from './views/list/list-model';
  import type { BoardData } from './board-data.svelte';

  interface Props {
    found: FoundCard;
    data: BoardData;
    view: string;
    onClose: () => void;
    el?: HTMLElement | null;
  }
  let { found, data, view, onClose, el = $bindable(null) }: Props = $props();
</script>

<aside class="sbcp" aria-label={t('swarm.board.list.detail')} bind:this={el} data-swarm-card-pane={view}>
  <div class="sbcp-bar">
    <button type="button" class="oc-btn oc-btn--sm" onclick={onClose} data-swarm-pane-close>{t('swarm.board.detail.close')}</button>
  </div>
  {#key found.card.id}
    <CardDetail card={found.card} laneName={found.laneName} companyName={found.companyName} {data} />
  {/key}
</aside>

<style>
  @layer components {
    .sbcp {
      container: swarm-list / inline-size;
      position: sticky;
      top: 0;
      min-width: 0;
      max-height: 100dvh;
      margin-left: 20px;
      overflow: auto;
      box-shadow: -1px 0 0 var(--oc-line-rule);
    }
    .sbcp-bar {
      display: flex;
      justify-content: flex-end;
      padding: 14px 36px 0;
    }
    @container swarm-board-shell (max-width: 720px) {
      .sbcp {
        order: -1;
        position: static;
        max-height: none;
        margin: 0 0 12px;
        box-shadow: 0 1px 0 var(--oc-line-rule);
      }
      .sbcp-bar {
        padding: 12px 16px 0;
      }
    }
  }
</style>

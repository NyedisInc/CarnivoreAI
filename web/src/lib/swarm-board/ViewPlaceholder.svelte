
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { COLUMNS } from './board-types';
  import type { BoardData } from './board-data.svelte';

  interface Props {
    view: 'list' | 'timeline' | 'calendar';
    data: BoardData;
  }
  let { view, data }: Props = $props();
  const total = $derived(data.lanes.reduce((n, lane) => n + COLUMNS.reduce((m, c) => m + lane.counts[c], 0), 0));
</script>

<div class="sbp" data-swarm-board-placeholder={view}>
  <span class="sbp-label">{t(`swarm.board.view.${view}`)}</span>
  <span class="sbp-text">{t('swarm.board.placeholder', { count: total })}</span>
</div>

<style>
  @layer components {
    .sbp {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      padding: var(--oc-space-5) 0;
      box-shadow: 0 1px 0 var(--oc-line-rule);
      font-family: var(--font-mono);
    }
    .sbp-label {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
    }
    .sbp-text {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-body);
    }
  }
</style>

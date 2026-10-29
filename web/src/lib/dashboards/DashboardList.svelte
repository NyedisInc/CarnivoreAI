<script lang="ts">
  import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
  import { dashboardLayout } from './board-layout';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { MAX_BOARDS } from '../../opscenter/engine/home-boards';
  import { t } from '../i18n/index.svelte';
  import DashboardCard from './DashboardCard.svelte';
  import { addDashboard, dashboardsFull, dashboardsUi } from './dashboard-actions.svelte';

  let { query = '', onEditHome = () => {} }: { query?: string; onEditHome?: () => void } = $props();

  const needle = $derived(query.trim().toLowerCase());
  const shown = $derived(
    [...homeBoards.list]
      .sort((a, b) => Number(b.id === homeBoards.active) - Number(a.id === homeBoards.active))
      .filter((board) => !needle || board.name.toLowerCase().includes(needle)),
  );
  const full = $derived(dashboardsFull());

  const layoutOf = dashboardLayout;
</script>

<section class="dash-list" data-dashboards aria-label={t('dashboards.list')}>
  <ul class="oc-page__items dash-list__grid">
    {#each shown as board (board.id)}
      <DashboardCard id={board.id} name={board.name} home={board.id === homeBoards.active} layout={layoutOf(board.id)} {onEditHome} />
    {/each}
    {#if !needle}
      <li class="dash-list__new-cell">
        <button
          type="button"
          class="dash-list__new"
          data-dashboard-new-tile
          disabled={full || dashboardsUi.busy}
          title={full ? t('dashboards.full', { max: MAX_BOARDS }) : ''}
          onclick={() => void addDashboard(false)}
          ><Icon name="plus" size={18} /><span class="dash-list__new-word">{t('dashboards.new')}</span><span class="dash-list__new-hint"
            >{t('dashboards.new_hint')}</span
          ></button
        >
      </li>
    {/if}
  </ul>
  {#if needle && shown.length === 0}
    <p class="dash-list__line" role="status">{t('dashboards.no_match')}</p>
  {/if}
  <p class="dash-list__line" role="status" data-dashboards-status>{dashboardsUi.notice}</p>
</section>

<style>
  @layer components {
    .dash-list {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-3);
      font-family: var(--font-mono);
    }

    .dash-list__grid {
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
    }

    .dash-list__new-cell {
      display: flex;
      min-width: 0;
    }

    .dash-list__new {
      display: flex;
      flex: 1 1 auto;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--oc-space-1);
      min-height: 180px;
      padding: var(--oc-space-3);
      border: var(--oc-border, 1px) dashed var(--oc-line-rule);
      border-radius: var(--oc-radius-sm, 2px);
      background: transparent;
      color: var(--oc-text-secondary);
      font-family: inherit;
      cursor: pointer;
    }

    .dash-list__new:hover:not(:disabled) {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    .dash-list__new:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }

    .dash-list__new-word {
      font-size: var(--oc-fs-status);
    }

    .dash-list__new-hint {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }

    .dash-list__line {
      margin: 0;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }
  }
</style>

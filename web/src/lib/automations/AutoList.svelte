
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import List from '../base/List.svelte';
  import State from '../base/State.svelte';
  import AutoRow from './AutoRow.svelte';
  import AutoToolbar from './AutoToolbar.svelte';
  import LogDock from './LogDock.svelte';
  import KeyHints from './KeyHints.svelte';
  import NewestRunLine from './NewestRunLine.svelte';
  import { automationMenuNodes, type RowMenuAction } from './row-menu-nodes';
  import ScheduledTree from './ScheduledTree.svelte';
  import { forwardMenuKey, type PageRowMenu } from '../item-menu/page-row';
  import './auto-list.css';
  import { duplicate, remove, resetFilters, startFromTemplate, view, visibleRows } from './list-state.svelte';
  import { SORT_KEYS, DESC_FIRST, type SortKey } from './logic/list';
  import { TEMPLATES, templateNameKey } from './logic/templates';
  import { data, openEdit, openNew, openPane, refresh, select } from './page-store.svelte';

  const rows = $derived(visibleRows());
  const byId = $derived(new Map(data.automations.map((a) => [a.automation_id, a])));
  const failed = $derived(data.status === 'error');
  const confirming = $derived(view.confirmId ? (byId.get(view.confirmId) ?? null) : null);
  let grid: HTMLDivElement | undefined = $state();

  const HEAD: [string, string, boolean][] = [
    ['light', 'light', true],
    ['name', 'name', true],
    ['next', 'next', true],
    ['last', 'last', true],
    ['strip', 'strip', false],
    ['rate', 'rate', true],
    ['med', 'med', true],
    ['on', 'on', true],
    ['', 'act', false],
  ];

  function sortOn(k: SortKey): void {
    view.sort = view.sort.k === k ? { k, d: view.sort.d > 0 ? -1 : 1 } : { k, d: DESC_FIRST.has(k) ? -1 : 1 };
  }

  function rowEl(id: string): HTMLElement | null {
    return [...(grid?.querySelectorAll<HTMLElement>('[data-automation]') ?? [])].find((el) => el.dataset.automation === id) ?? null;
  }

  function pick(id: string, openIt = false): void {
    select(id);
    if (openIt) openPane();
    rowEl(id)?.scrollIntoView?.({ block: 'nearest' });
  }

  function rowClick(id: string, e: MouseEvent): void {
    if ((e.target as Element).closest('button, input, select, a')) return;
    pick(id, true);
    (e.currentTarget as HTMLElement).focus({ preventScroll: true });
  }

  function rowMenu(id: string): PageRowMenu {
    return { type: 'pagerow', ctx: { label: t('automations.page.menu.aria'), nodes: automationMenuNodes((action) => menuPick(id, action)) }, onOpen: () => pick(id) };
  }

  function keys(e: KeyboardEvent): void {
    if (!rows.length || (e.target as Element).closest('input, select, textarea, [data-scheduled-tree]')) return;
    const at = rows.findIndex((r) => r.id === data.selectedId);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = rows[Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : at + (e.key === 'ArrowDown' ? 1 : -1)))]!;
      pick(next.id);
      rowEl(next.id)?.focus({ preventScroll: true });
    } else if (forwardMenuKey(e, data.selectedId ? rowEl(data.selectedId) : null)) {
    } else if (e.key === 'Enter' && !(e.target as Element).closest('button') && data.selectedId) {
      e.preventDefault();
      openPane();
    }
  }

  function menuPick(id: string, action: RowMenuAction): void {
    const a = byId.get(id);
    if (!a) return;
    if (action === 'edit') openEdit(a.automation_id);
    else if (action === 'duplicate') void duplicate(a);
    else view.confirmId = a.automation_id;
  }

  async function retry(): Promise<void> {
    await refresh();
    if (data.status === 'error') data.notice = t('automations.page.toast.list_still_failed');
  }
</script>

<div class="ap-listcol" data-density={view.dens}>
  {#if failed}
    <State kind="error" title={t('automations.read_failed', { reason: data.error })} data-automations-error="" data-list-error="">
      {#snippet actions()}<Button size="sm" data-list-retry onclick={() => void retry()}>{t('automations.page.try_again')}</Button>{/snippet}
    </State>
    {#if data.logOpen}<LogDock onClose={() => (data.logOpen = false)} />{/if}
  {:else}
    <AutoToolbar shown={rows.length} />
    {#if confirming}
      <State kind="warn" inline role="group" title={t('automations.delete_confirm', { name: confirming.name })} data-auto-confirm>
        {#snippet actions()}
          <Button size="sm" onclick={() => (view.confirmId = null)}>{t('automations.delete_keep')}</Button>
          <Button variant="danger" size="sm" data-automation-delete-confirm onclick={() => void remove(confirming)}>{t('automations.delete_go')}</Button>
        {/snippet}
      </State>
    {/if}
    <List
      class="ap-list"
      bind:element={grid}
      role="grid"
      tabindex={0}
      label={t('automations.page.list.aria')}
      data-auto-list=""
      density={view.dens === 'compact' ? 'dense' : 'roomy'}
      onkeydown={keys}
    >
      {#if !data.automations.length}
        <State title={t('automations.empty')} data-auto-empty="">
          {#snippet actions()}
            <Button variant="confirm" size="sm" data-new disabled={!data.targets} onclick={() => openNew()}>{t('automations.new')}</Button>
            {#each TEMPLATES.slice(0, 3) as tpl, i (tpl.id)}
              <Button size="sm" data-tpl={i} disabled={!data.targets} onclick={() => startFromTemplate(tpl)}>{t(templateNameKey(tpl))}</Button>
            {/each}
          {/snippet}
        </State>
      {:else}
        <div class="ap-lhead" role="row">
          {#each HEAD as [key, cls, sortable] (cls)}
            {#if !key && !sortable}
              <span class="ap-c-{cls}"></span>
            {:else}
              {@const on = sortable && view.sort.k === key}
              <span class="ap-c-{cls} ap-hcw" role="columnheader" aria-sort={on ? (view.sort.d > 0 ? 'ascending' : 'descending') : undefined}>
                {#if sortable}
                  <Button variant="quiet" size="sm" data-sort={key} onclick={() => sortOn(key as SortKey)}>
                    {#if key === 'light'}<span class="ap-sr">{t('automations.page.col.health')}</span><span aria-hidden="true">&nbsp;</span>{:else}{t(`automations.page.col.${key}`)}{/if}
                    <span class="ap-arr" aria-hidden="true" data-d={on ? (view.sort.d > 0 ? 'up' : 'down') : undefined}></span>
                  </Button>
                {:else}
                  <span class="ap-hc ap-hc--plain">{t(`automations.page.col.${key}`)}</span>
                {/if}
              </span>
            {/if}
          {/each}
        </div>
        {#if rows.length}
          {#each rows as row (row.id)}
            {@const a = byId.get(row.id)}
            {#if a}
              <AutoRow
                automation={a}
                {row}
                selected={data.selectedId === row.id}
                onPick={(e) => rowClick(row.id, e)}
                menu={() => rowMenu(row.id)}
              />
            {/if}
          {/each}
        {:else}
          <State title={t('automations.page.list.no_match')} data-auto-nomatch="">
            {#snippet actions()}<Button size="sm" data-clear onclick={resetFilters}>{t('automations.page.clear_filters')}</Button>{/snippet}
          </State>
        {/if}
      {/if}
      <ScheduledTree />
    </List>
    {#if data.logOpen}<LogDock onClose={() => (data.logOpen = false)} />{/if}
    {#if data.automations.length}<NewestRunLine />{/if}
    <KeyHints />
  {/if}
</div>

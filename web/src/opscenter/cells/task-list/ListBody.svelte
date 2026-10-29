<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { truncatedTip } from '../../../lib/tooltip/truncated-tip';
  import ListRow from './ListRow.svelte';
  import { statusKey } from '../../../cplugs/huddle/huddle-status';
  import { badgeLabelKey } from '../../../cplugs/huddle/task-manager-badge-menu';
  import type { BadgeStatus } from '../../../cplugs/huddle/task-manager-prefs.svelte';
  import { LIST_ORDER, sectionsOf, type ListDensity, type ListGroupBy, type ListRow as Row, type ListSection } from './model';

  let { rows, limit = null, density, grouping, heads = true }: {
    rows: Row[];
    limit?: number | null;
    density: ListDensity;
    grouping: ListGroupBy;
    heads?: boolean;
  } = $props();

  $effect(() => startClock());

  const shown = $derived(limit === null ? rows : rows.slice(0, limit));
  const sections = $derived(sectionsOf(shown, grouping));
  let openId = $state<string | null>(null);
  const frozenAt = clock.frozen ? Date.now() : null;
  const nowMs = $derived.by(() => {
    void clock.now;
    return frozenAt ?? Date.now();
  });

  $effect(() => {
    if (openId !== null && !rows.some((row) => keyOf(row) === openId)) openId = null;
  });

  const keyOf = (row: Row): string => row.key ?? String(row.id);

  function headWords(section: ListSection): string {
    return section.by === 'status' && section.status ? t((LIST_ORDER as readonly string[]).includes(section.status) ? badgeLabelKey(section.status as BadgeStatus) : statusKey(section.status)) : section.label;
  }
</script>

<div class="hl-cell" data-task-manager-list-cell data-density={density}>
  {#if rows.length === 0}
    <p class="hl-empty" data-task-manager-list-empty>{t('opscenter.cell.task_list.empty')}</p>
  {:else}
    <ul class="hl-list" aria-label={t('opscenter.cell.task_list.list')}>
      {#each sections as section (section.key)}
        {#if heads}
          <li class="hl-head" data-task-manager-list-head={section.key} data-group={section.by} role="presentation">
            <span class="hl-head__label" use:truncatedTip={headWords(section)}>{headWords(section)}</span>
            <span class="hl-head__count">{section.rows.length}</span>
          </li>
        {/if}
        {#each section.rows as row (keyOf(row))}
          <ListRow {row} {density} open={openId === keyOf(row)} {nowMs} onToggle={() => (openId = openId === keyOf(row) ? null : keyOf(row))} onClose={() => (openId = null)} />
        {/each}
      {/each}
    </ul>
  {/if}
</div>

<style>
  @layer components {
    .hl-cell {
      position: relative;
      height: 100%;
      min-height: 0;
      overflow-y: auto;
      font-family: var(--font-mono);
      container: oc-hl / inline-size;
    }

    .hl-list { list-style: none; margin: 0; padding: 0; }

    .hl-head {
      display: flex;
      align-items: center;
      gap: 6px;
      height: 18px;
      padding: 0 10px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .hl-head__label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .hl-head__count { flex: none; color: var(--oc-text-muted); }

    .hl-empty {
      margin: 0;
      padding: var(--oc-space-3);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }
  }
</style>

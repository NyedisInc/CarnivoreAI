<script lang="ts">
  import Icon from '../../ui/Icon.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { STATUS_ICON, statusIconColor, statusKey } from '../../../cplugs/huddle/huddle-status';
  import { truncatedTip } from '../../../lib/tooltip/truncated-tip';
  import { ageWords } from './age';
  import ApproveKey from './ApproveKey.svelte';
  import ListRowOpen from './ListRowOpen.svelte';
  import type { ListDensity, ListRow } from './model';

  let { row, density, open, nowMs, onToggle, onClose }: {
    row: ListRow; density: ListDensity; open: boolean; nowMs: number; onToggle: () => void; onClose: () => void;
  } = $props();

  const question = $derived(row.status === 'question');
  const review = $derived(row.status === 'review');
  const age = $derived(row.atMs === null ? '' : ageWords(row.atMs, nowMs, row.status === 'scheduled'));
  const state = $derived(t(statusKey(row.status)));
</script>

<li class="hl-row" class:hl-row--q={question} class:hl-row--review={review} class:hl-row--open={open} data-task-manager-list-row={row.id} data-status={row.status}>
  <button type="button" class="hl-sum" class:hl-sum--full={density === 'full'} aria-expanded={open} onclick={onToggle}>
    <span class="hl-mark" style:color={statusIconColor(row.status)} title={state}><Icon name={STATUS_ICON[row.status]} size={12} /></span>
    <span class="hl-title" use:truncatedTip={row.title}>{row.title}</span>
    <span class="hl-age" class:hl-age--q={question}>{age}</span>
    {#if density === 'full'}
      <span class="hl-line2" data-huddle-list-line2>
        {#if row.who}<span class="hl-who" class:hl-who--claude={row.who === 'claude'}>{t(`opscenter.cell.task_list.who.${row.who}`)}</span>{/if}
        <span use:truncatedTip={row.last}>{row.last}</span>
      </span>
    {/if}
  </button>
  {#if review}<span class="hl-approve-slot"><ApproveKey item={row.item} /></span>{/if}
  {#if open}<ListRowOpen {row} {onClose} />{/if}
</li>

<style>
  @layer components {
    .hl-row {
      position: relative;
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hl-row--q::before {
      content: '';
      position: absolute;
      inset: 0 auto 0 0;
      width: 2px;
      background: var(--oc-yellow-bright);
    }

    .hl-row--open { background: var(--oc-ground-card); }

    .hl-row--review > .hl-sum { padding-right: 34px; }

    .hl-approve-slot { position: absolute; top: 0; right: 6px; display: inline-flex; align-items: center; height: 20px; }

    .hl-sum {
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr) auto;
      column-gap: 6px;
      align-items: center;
      width: 100%;
      height: 20px;
      padding: 0 10px;
      border: 0;
      background: none;
      color: var(--oc-text-primary);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }

    .hl-sum:hover { background: var(--oc-ground-hover); }
    .hl-row--open .hl-sum:hover { background: none; }

    .hl-sum--full {
      height: 36px;
      grid-template-rows: 16px 14px;
      row-gap: 1px;
      align-content: center;
    }

    .hl-mark { grid-row: 1; display: inline-flex; }

    .hl-title {
      grid-row: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: var(--oc-fs-label);
    }

    .hl-age {
      grid-row: 1;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      white-space: nowrap;
    }

    .hl-age--q { color: var(--oc-yellow-bright); }

    .hl-line2 {
      grid-column: 2 / 4;
      grid-row: 2;
      display: flex;
      gap: 5px;
      align-items: center;
      min-width: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .hl-line2 > span {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hl-who { flex: none; color: var(--oc-text-dim); }
    .hl-who--claude { color: var(--oc-orange); }
  }
</style>

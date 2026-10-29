<script lang="ts">
  /* the widget menu */
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { clearViewFilter, setViewChip, setViewQuery, viewFilter, viewFilterActive, type ViewChip } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
  import { hiddenSections, setSectionHidden } from '../../../cplugs/huddle/task-manager-status-folds.svelte';
  import Icon from '../../ui/Icon.svelte';
  import { titleWhenTruncated } from '../../../lib/base/truncate';
  import { t } from '../../../lib/i18n/index.svelte';
  import { MK2_CHIP_ICON, MK2_CHIP_LABEL, MK2_CHIP_ORDER, MK2_CHIP_TEST, chipCount, chipMode, type Mk2ChipId } from './mk2-chips';

  let { items }: { items: HuddleItem[] } = $props();

  const everything = $derived(!viewFilterActive() && hiddenSections.keys.length === 0);

  let width = $state(0);
  let bar = $state<HTMLElement | null>(null);
  const mode = $derived(chipMode(width));

  $effect(() => {
    const box = bar;
    if (!box || typeof ResizeObserver === 'undefined') return;
    const measure = (): void => { width = box.clientWidth; };
    const watch = new ResizeObserver(measure);
    watch.observe(box);
    measure();
    return () => watch.disconnect();
  });

  function pressed(id: Mk2ChipId): boolean {
    if (id === 'all') return everything;
    return viewFilter.chip === id;
  }

  function countOf(id: Mk2ChipId): number | null {
    return id === 'all' ? null : chipCount(id, items);
  }

  function wordsOf(id: Mk2ChipId, count: number | null): string {
    return count ? `${t(MK2_CHIP_LABEL[id])} (${count})` : t(MK2_CHIP_LABEL[id]);
  }

  function press(id: Mk2ChipId): void {
    if (id === 'all') {
      clearViewFilter();
      for (const key of [...hiddenSections.keys]) setSectionHidden(key, false);
    } else {
      const chip: ViewChip = id;
      setViewChip(viewFilter.chip === chip ? null : chip, MK2_CHIP_TEST[chip]);
    }
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || viewFilter.query === '') return;
    event.preventDefault();
    setViewQuery('');
  }
</script>

<div class="mk2-bar" data-task-manager-mk2-bar data-mk2-chip-mode={mode} bind:this={bar}>
  <div class="mk2-search">
    <input class="mk2-field" data-field data-size="sm" type="search" autocomplete="off" spellcheck="false" value={viewFilter.query}
           placeholder={t('cplug.huddle.search.placeholder')} aria-label={t('cplug.huddle.search.placeholder')} data-task-manager-search
           oninput={(event) => setViewQuery((event.currentTarget as HTMLInputElement).value)} onkeydown={onKey} />
  </div>
  <div class="mk2-chips" role="group" aria-label={t('opscenter.cell.task_manager_mk2.chips_label')} data-task-manager-mk2-chips>
    {#each MK2_CHIP_ORDER as id (id)}
      {@const count = countOf(id)}
      <button type="button" class="oc-chip mk2-chip" data-btn="secondary" data-size="sm" use:titleWhenTruncated={'.mk2-chip-label'} aria-pressed={pressed(id)} aria-label={wordsOf(id, count)} title={wordsOf(id, count)} data-task-manager-mk2-chip={id} onclick={() => press(id)}>
        <span class="mk2-chip-icon" aria-hidden="true"><Icon name={MK2_CHIP_ICON[id]} size={12} strokeWidth={2} /></span><span class="mk2-chip-label">{t(MK2_CHIP_LABEL[id])}</span>{#if count}<span class="mk2-chip-count">{count}</span>{/if}
      </button>
    {/each}
  </div>
</div>

<style>
  @layer components {
    .mk2-bar {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      padding: var(--oc-space-2);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .mk2-search {
      display: flex;
      min-width: 0;
    }

    .mk2-field {
      flex: 1 1 auto;
      min-width: 0;
      height: 20px;
      font-size: var(--oc-fs-label);
    }

    .mk2-chips {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .mk2-chip {
      --_btn-h: 20px;
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      height: 20px;
      min-width: 0;
      max-width: 100%;
      padding-block: 0;
      white-space: nowrap;
    }

    .mk2-chip-label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .mk2-chip-icon {
      display: none;
      align-items: center;
    }

    .mk2-bar:is([data-mk2-chip-mode='count'], [data-mk2-chip-mode='icon']) .mk2-chip-icon {
      display: inline-flex;
    }

    .mk2-bar:is([data-mk2-chip-mode='count'], [data-mk2-chip-mode='icon']) .mk2-chip-label {
      display: none;
    }

    .mk2-bar[data-mk2-chip-mode='icon'] .mk2-chip-count {
      display: none;
    }

    .mk2-chip-count {
      font-variant-numeric: tabular-nums;
      opacity: 0.8;
    }
  }
</style>

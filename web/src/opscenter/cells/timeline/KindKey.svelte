<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import { FILTER_KEYS } from './model';
  import type { FilterKey, Filters } from './types';
  import KindGlyph from './KindGlyph.svelte';
  import { tx } from './strings';

  let { filters, counts, form, onToggle }: { filters: Filters; counts: Record<FilterKey, number>; form: 'glyphs' | 'counts' | 'words'; onToggle: (key: FilterKey) => void } = $props();

  const GLYPH: Readonly<Record<FilterKey, 'compact' | 'bookmark' | 'restart' | 'restore' | 'sleep'>> = {
    bookmarks: 'bookmark', compacts: 'compact', restarts: 'restart', sleeps: 'sleep', restores: 'restore',
  };
</script>

<div class="tlx-key" role="group" aria-label={t('opscenter.cell.timeline.filters')} data-timeline-key>
  {#each FILTER_KEYS as key (key)}
    {@const name = t(`opscenter.cell.timeline.filter.${key}`)}
    {@const label = counts[key] === 0 ? tx('key.none', { kind: name }) : tx('key.label', { kind: name, count: counts[key] })}
    <button type="button" class="tlx-key__btn" data-filter={key} data-empty={counts[key] === 0 || undefined}
      aria-pressed={filters[key]} aria-label={label} title={label} onclick={() => onToggle(key)}>
      <KindGlyph kind={GLYPH[key]} off={!filters[key]} />
      {#if form !== 'glyphs'}<span class="tlx-key__n">{counts[key]}</span>{/if}
      {#if form === 'words'}<span class="tlx-key__word">{name}</span>{/if}
    </button>
  {/each}
</div>

<style>
  @layer components {
    .tlx-key {
      display: flex;
      align-items: center;
      gap: var(--oc-space-0-5);
      min-width: 0;
    }

    .tlx-key__btn {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      height: 1.375rem;
      padding: 0 calc(var(--oc-space-1) + var(--oc-border));
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: none;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      white-space: nowrap;
      cursor: pointer;
    }

    .tlx-key__btn:hover {
      border-color: var(--oc-line-panel);
      background: var(--oc-ground-hover);
    }

    .tlx-key__btn[aria-pressed='false'] {
      color: var(--oc-text-muted);
    }

    .tlx-key__btn[aria-pressed='false'] .tlx-key__word {
      text-decoration: line-through;
    }

    .tlx-key__btn[data-empty] {
      color: var(--oc-text-muted);
    }

    .tlx-key__n {
      font-variant-numeric: tabular-nums;
    }
  }
</style>

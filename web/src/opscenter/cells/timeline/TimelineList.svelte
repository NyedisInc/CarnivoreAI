<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { beganWord, kindWord, markTitle, when } from './format';
  import type { ListRow } from './model';
  import type { Mark } from './types';

  let { rows, selectedId, onSelect, card }: { rows: readonly ListRow[]; selectedId: string | null; onSelect: (mark: Mark) => void; card: Snippet<[Mark]> } = $props();
</script>

<ol class="oc-tl-list" data-timeline-list>
  {#each rows as row (row.key)}
    {#if row.type === 'began'}
      <li class="oc-tl-row oc-tl-row--bar" data-list-bar={row.bar.conversation_id} data-current={row.bar.current || undefined}>
        <span class="oc-tl-rowkind">{beganWord(row.bar)}</span>
        <span class="oc-tl-rowwhen">{when(row.at)}</span>
        {#if row.bar.began?.split}<span class="oc-tl-rowwhen">{t('opscenter.cell.timeline.cut_from')}</span>{/if}
      </li>
    {:else if row.type === 'gap'}
      <li class="oc-tl-row oc-tl-row--gap" data-list-gap={row.gap.id}>
        <span class="oc-tl-rowkind">{t('opscenter.cell.timeline.kind.sleep')}</span>
        <span class="oc-tl-rowwhen">{row.gap.end ? t('opscenter.cell.timeline.sleep.span', { from: when(row.gap.start), to: when(row.gap.end) }) : t('opscenter.cell.timeline.sleep.open', { from: when(row.gap.start) })}</span>
      </li>
    {:else}
      <li class="oc-tl-row" data-list-mark={row.mark.id} data-kind={row.mark.kind}>
        <button type="button" class="oc-tl-rowline" data-btn="row" aria-expanded={selectedId === row.mark.id} onclick={() => onSelect(row.mark)}>
          <span class="oc-tl-dot" data-kind={row.mark.kind} aria-hidden="true"></span>
          <span class="oc-tl-rowkind">{kindWord(row.mark)}</span>
          <span class="oc-tl-rowtitle">{markTitle(row.mark)}</span>
          <span class="oc-tl-rowwhen">{when(row.mark.at)}</span>
        </button>
        {#if selectedId === row.mark.id}{@render card(row.mark)}{/if}
      </li>
    {/if}
  {/each}
</ol>

<style>
  @layer components {
    .oc-tl-list {
      display: flex;
      flex-direction: column;
      margin: 0;
      padding: 0;
      list-style: none;
      font-family: var(--font-mono);
    }

    .oc-tl-row {
      min-width: 0;
    }

    .oc-tl-row:not(:first-child) {
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .oc-tl-row--bar,
    .oc-tl-row--gap {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
    }

    .oc-tl-row--bar {
      box-shadow: 0 1px 0 var(--oc-line-rule);
    }

    .oc-tl-row--bar[data-current] .oc-tl-rowkind {
      color: var(--oc-cyan);
    }

    .oc-tl-row--gap {
      color: var(--oc-text-dim);
    }

    .oc-tl-rowline {
      width: 100%;
      min-height: var(--oc-tap);
      padding: var(--oc-space-1) var(--oc-space-3);
      color: var(--oc-text-primary);
      font: inherit;
    }

    .oc-tl-rowline[aria-expanded='true'] {
      background: var(--oc-ground-hover);
    }

    .oc-tl-rowkind {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
    }

    .oc-tl-rowtitle {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      font-size: var(--oc-fs-body);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .oc-tl-rowwhen {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .oc-tl-dot {
      flex: none;
      width: 0.5rem;
      height: 0.5rem;
      background: var(--_hue, var(--oc-text-secondary));
    }

    .oc-tl-dot[data-kind='compact'] { --_hue: var(--oc-violet); transform: rotate(45deg); }
    .oc-tl-dot[data-kind='bookmark'] { --_hue: var(--oc-yellow); }
    .oc-tl-dot[data-kind='restart'] { --_hue: var(--oc-green); border-radius: 50%; }
    .oc-tl-dot[data-kind='restore'] { --_hue: var(--oc-cyan); background: none; border: var(--oc-border) solid var(--_hue); }
  }
</style>

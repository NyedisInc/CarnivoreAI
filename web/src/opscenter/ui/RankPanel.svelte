
<script lang="ts" module>
  export interface RankRow {
    readonly id: string;
    readonly name: string;
    readonly line?: string | null;
    readonly icon?: string;
    readonly iconSvg?: string;
    readonly tags?: readonly string[];
    readonly metric: { readonly value: string; readonly unit?: string } | null;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  interface Props {
    label: string;
    rows: readonly RankRow[];
    ranked?: boolean;
    columns?: { readonly name: string; readonly metric: string };
    viewAll?: string;
    onViewAll?: () => void;
    notMeasured: string;
    empty?: string;
    headExtra?: Snippet;
    lead?: Snippet<[RankRow]>;
    trail?: Snippet<[RankRow]>;
    separated?: boolean;
    /* the reading pane */
    onSelect?: (id: string) => void;
  }

  const { label, rows, ranked = false, columns, viewAll, onViewAll, notMeasured, empty, headExtra, lead, trail, separated = false, onSelect }: Props = $props();

  const uid = `rank-${Math.random().toString(36).slice(2, 9)}`;
</script>

<section class="oc-rank" class:oc-rank--split={separated} aria-labelledby="{uid}-label">
  <header class="oc-rank__head">
    <h3 class="oc-rank__label" id="{uid}-label">{label}</h3>
    {#if headExtra}<div class="oc-rank__head-extra">{@render headExtra()}</div>{/if}
    {#if viewAll && onViewAll}
      <button type="button" class="oc-btn oc-btn--ghost oc-btn--sm" onclick={onViewAll}>{viewAll}</button>
    {/if}
  </header>
  {#if columns}
    <div class="oc-rank__cols" aria-hidden="true">
      <div class="oc-rank__cols-set"><span>{columns.name}</span><span>{columns.metric}</span></div>
      <div class="oc-rank__cols-set oc-rank__cols-set--second"><span>{columns.name}</span><span>{columns.metric}</span></div>
    </div>
  {/if}
  {#if rows.length === 0}
    {#if empty}<div class="oc-rank__empty">{empty}</div>{/if}
  {:else}
    <div class="oc-rank__rows" class:oc-rank__rows--ranked={ranked} role="list">
      {#each rows as row, index (row.id)}
        <div class="oc-rank__row" role="listitem" data-rank-row={row.id}>
          {#if ranked}<span class="oc-rank__num">{index + 1}</span>{/if}
          <span class="oc-rank__who">
            {#if lead}{@render lead(row)}{/if}
            <span class="oc-icon-tile oc-rank__tile">{#if row.iconSvg}{@html row.iconSvg}{:else if row.icon}<Icon name={row.icon} size={12} />{:else}<span class="oc-rank__letter" aria-hidden="true">{row.name.charAt(0).toUpperCase()}</span>{/if}</span>
          </span>
          <span class="oc-rank__text">
            <span class="oc-rank__name">{#if onSelect}<button type="button" class="oc-rank__open" onclick={() => onSelect(row.id)}>{row.name}</button>{:else}{row.name}{/if}</span>
            {#if row.tags?.length || row.line}
              <span class="oc-rank__sub">
                {#each row.tags ?? [] as tag (tag)}<span class="oc-rank__tag">{tag}</span>{/each}
                {#if row.line}<span class="oc-rank__line">{row.line}</span>{/if}
              </span>
            {/if}
          </span>
          <span class="oc-rank__metric">
            {#if trail}{@render trail(row)}{/if}
            {#if row.metric}
              <span class="oc-rank__value">{row.metric.value}</span>{#if row.metric.unit}<span class="oc-rank__unit">{row.metric.unit}</span>{/if}
            {:else}
              <span class="oc-rank__unit">{notMeasured}</span>
            {/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</section>

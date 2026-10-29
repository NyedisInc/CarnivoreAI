<script lang="ts" generics="Row extends Record<string, unknown>">
  /* running sessions */
  import type { Snippet } from 'svelte';
  import type { ColumnSpec } from '../engine/types';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    columns,
    rows,
    rowHeight = 26,
    headHeight = 26,
    bodyType = 'oc-fs-body',
    headType = 'oc-fs-label',
    showHead = true,
    compact = false,
    rowKey,
    rowIdAttr,
    onActivate,
    canActivate,
    rowLabel,
    cell,
  }: {
    columns: ColumnSpec[];
    rows: Row[];
    rowHeight?: number;
    headHeight?: number;
    bodyType?: string;
    headType?: string;
    showHead?: boolean;
    compact?: boolean;
    rowKey: (row: Row, index: number) => string;
    rowIdAttr?: string;
    /* <button> role="button" */
    onActivate?: (row: Row, index: number) => void;
    canActivate?: (row: Row, index: number) => boolean;
    rowLabel?: (row: Row, index: number) => string;
    cell: Snippet<[Row, ColumnSpec, number]>;
  } = $props();

  function onRowKey(event: KeyboardEvent, row: Row, index: number): void {
    if (!onActivate) return;
    if (canActivate && !canActivate(row, index)) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onActivate(row, index);
  }

  const tracks = $derived(columns.map((column) => `minmax(${trackMin(column)}, ${column.weight}fr)`).join(' '));

  /* padding */
  const CELL_PAD_PX = 10;

  /* padding */
  function trackMin(column: ColumnSpec): string {
    if (column.minCh === undefined) return `${column.minPx}px`;
    const head = column.headKey ? t(column.headKey).length + 1 : 0;
    const chars = Math.max(column.minCh, head);
    return `max(${column.minPx}px, calc(${chars}ch + ${CELL_PAD_PX + (column.insetPx ?? CELL_PAD_PX)}px))`;
  }

  const lineOne = $derived(columns.filter((column) => column.line !== 2));
  const lineTwo = $derived(columns.filter((column) => column.line === 2));

  function lineTracks(list: ColumnSpec[]): string {
    return list.map((column) => (column.weight > 0 ? `minmax(0, ${column.weight}fr)` : 'auto')).join(' ');
  }

  function acts(row: Row, index: number): boolean {
    if (!onActivate) return false;
    return canActivate ? canActivate(row, index) : true;
  }

  function cellStyle(column: ColumnSpec, inset: number | undefined): string {
    const parts: string[] = [];
    if (column.align === 'end') parts.push('justify-content:flex-end');
    if (inset !== undefined) {
      parts.push(`${column.align === 'end' ? 'padding-right' : 'padding-left'}:${inset}px`);
    }
    return parts.join(';');
  }
</script>

<div
  class="oc-table"
  style={`--oc-table-tracks: ${tracks}; --oc-table-rowheight: ${rowHeight}px; --oc-table-headheight: ${headHeight}px; --oc-table-fs-body: var(--${bodyType}); --oc-table-fs-head: var(--${headType})`}
>
  {#if showHead && !compact}
    <div class="oc-table-head" role="row">
      {#each columns as column (column.key)}
        <span
          class="oc-table-cell oc-table-headcell"
          data-col={column.key}
          style={cellStyle(column, column.headInsetPx ?? column.insetPx)}
        >
          {column.headKey ? t(column.headKey) : ''}
        </span>
      {/each}
    </div>
  {/if}
  <div class="oc-table-body">
    {#each rows as row, index (rowKey(row, index))}
      {#if compact}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <!-- role="button" -->
        <div
          class="oc-table-row oc-table-row-compact"
          class:oc-table-row-action={acts(row, index)}
          data-row={rowKey(row, index)}
          {...rowIdAttr ? { [rowIdAttr]: rowKey(row, index) } : {}}
          role={acts(row, index) ? 'button' : undefined}
          tabindex={acts(row, index) ? 0 : undefined}
          aria-label={acts(row, index) ? rowLabel?.(row, index) : undefined}
          onclick={acts(row, index) ? () => onActivate?.(row, index) : undefined}
          onkeydown={acts(row, index) ? (event) => onRowKey(event, row, index) : undefined}
        >
          <div class="oc-table-line" style={`grid-template-columns: ${lineTracks(lineOne)}`}>
            {#each lineOne as column (column.key)}
              <span class="oc-table-cell" data-col={column.key} style={cellStyle(column, undefined)}>
                {@render cell(row, column, index)}
              </span>
            {/each}
          </div>
          {#if lineTwo.length}
            <div class="oc-table-line oc-table-line-2" style={`grid-template-columns: ${lineTracks(lineTwo)}`}>
              {#each lineTwo as column (column.key)}
                <span class="oc-table-cell" data-col={column.key} style={cellStyle(column, undefined)}>
                  {@render cell(row, column, index)}
                </span>
              {/each}
            </div>
          {/if}
        </div>
      {:else}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <!-- role="button" -->
        <div
          class="oc-table-row"
          class:oc-table-row-action={acts(row, index)}
          data-row={rowKey(row, index)}
          {...rowIdAttr ? { [rowIdAttr]: rowKey(row, index) } : {}}
          role={acts(row, index) ? 'button' : undefined}
          tabindex={acts(row, index) ? 0 : undefined}
          aria-label={acts(row, index) ? rowLabel?.(row, index) : undefined}
          onclick={acts(row, index) ? () => onActivate?.(row, index) : undefined}
          onkeydown={acts(row, index) ? (event) => onRowKey(event, row, index) : undefined}
        >
          {#each columns as column (column.key)}
            <span class="oc-table-cell" data-col={column.key} style={cellStyle(column, column.insetPx)}>
              {@render cell(row, column, index)}
            </span>
          {/each}
        </div>
      {/if}
    {/each}
  </div>
</div>

<style>
  @layer components {
    .oc-table {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
    }

    .oc-table-head,
    .oc-table-row {
      display: grid;
      grid-template-columns: var(--oc-table-tracks);
      min-width: 0;
      align-items: stretch;
    }

    .oc-table-head {
      position: sticky;
      top: 0;
      z-index: 1;
      height: var(--oc-table-headheight);
      background: var(--oc-ground-panel);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
      color: var(--oc-text-secondary);
      font-size: var(--oc-table-fs-body);
      letter-spacing: var(--oc-tracking-label);
      text-transform: uppercase;
    }

    .oc-table-headcell {
      font-size: var(--oc-table-fs-head);
    }

    .oc-table-row {
      height: var(--oc-table-rowheight);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
      color: var(--oc-text-primary);
      font-size: var(--oc-table-fs-body);
    }

    .oc-table-row:last-child {
      box-shadow: none;
    }

    .oc-table-row-action {
      cursor: pointer;
    }

    .oc-table-row-action:hover {
      background: var(--oc-ground-hover, var(--oc-ground-chrome));
    }

    .oc-table-cell {
      display: flex;
      align-items: center;
      min-width: 0;
      padding: 0 10px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      box-shadow: inset 1px 0 0 0 var(--oc-line-column);
    }

    .oc-table-cell:first-child {
      box-shadow: none;
    }

    .oc-table-row-compact {
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      height: auto;
      min-height: var(--oc-tap);
      padding: 6px 10px;
    }

    .oc-table-line {
      display: grid;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .oc-table-line-2 {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
    }

    .oc-table-row-compact .oc-table-cell {
      padding: 0;
      box-shadow: none;
    }
  }
</style>

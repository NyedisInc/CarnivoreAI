<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { FxRow } from './model';
  import type { GitTag } from '../../../lib/file-drawer/git-tags';

  let {
    row,
    focused,
    tag = null,
    label,
    sub = '',
    title = '',
    readOnlyMark = '',
    readOnlyLabel = '',
    tagLabel = '',
    summary,
    onActivate,
    onFocusRow,
  }: {
    row: FxRow;
    focused: boolean;
    tag?: GitTag | null;
    label: string;
    sub?: string;
    title?: string;
    readOnlyMark?: string;
    readOnlyLabel?: string;
    tagLabel?: string;
    summary?: Snippet;
    onActivate: (row: FxRow, alt: boolean) => void;
    onFocusRow: (key: string) => void;
  } = $props();

  const expandable = $derived(row.kind === 'section' || row.kind === 'group' || (row.kind === 'node' && row.node.is_dir));
  const open = $derived(row.kind === 'section' || row.kind === 'group' || row.kind === 'node' ? row.open : false);
  const interactive = $derived(row.kind !== 'note' || row.retry !== null);
  const dim = $derived(row.kind === 'node' && !!row.node.is_ignored);
</script>


<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="fx-row"
  data-kind={row.kind}
  data-key={row.key}
  data-git-tone={tag?.tone}
  data-note={row.kind === 'note' ? row.code : undefined}
  class:fx-row--dim={dim}
  class:fx-row--focus={focused}
  style:--fx-depth={row.depth}
  role="treeitem"
  aria-level={row.depth + 1}
  aria-expanded={expandable ? open : undefined}
  aria-selected={focused}
  aria-disabled={interactive ? undefined : true}
  tabindex={focused ? 0 : -1}
  {title}
  onclick={(event) => { if (!interactive) return; onFocusRow(row.key); onActivate(row, event.shiftKey); }}
  onfocus={() => onFocusRow(row.key)}
>
  <span class="fx-guides" aria-hidden="true"></span>
  <span class="fx-chev" aria-hidden="true">
    {#if expandable}
      <svg viewBox="0 0 10 10" width="10" height="10" class:fx-chev--open={open}><path d="M3 1.5 L7 5 L3 8.5" /></svg>
    {/if}
  </span>
  {#if row.kind === 'section'}
    <span class="fx-label">{label}</span>
    {#if sub}<bdi class="fx-sub">{sub}</bdi>{/if}
    <span class="fx-fill"></span>
    {#if summary}{@render summary()}{/if}
  {:else}
    <bdi class="fx-name">{label}</bdi>
    {#if sub}<bdi class="fx-sub fx-sub--path">{sub}</bdi>{/if}
    <span class="fx-fill"></span>
    {#if row.kind === 'node' && row.node.read_only}<span class="fx-ro" aria-label={readOnlyLabel}>{readOnlyMark}</span>{/if}
    <span class="fx-mark" aria-label={tagLabel || undefined}>{tag?.letter ?? ''}</span>
  {/if}
</div>

<style>
  @layer components {
    .fx-row {
      --fx-indent: 12px;
      box-sizing: border-box;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
      height: 22px;
      padding: 0 var(--oc-space-2) 0 calc(var(--fx-depth) * var(--fx-indent) + var(--oc-space-0-5));
      position: relative;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
      line-height: 22px;
      color: var(--oc-text-primary);
      white-space: nowrap;
      cursor: pointer;
      /* reserved 1px border */
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
    }

    .fx-row:hover,
    .fx-row--focus {
      background: var(--oc-ground-hover);
    }

    .fx-row[aria-disabled='true'] {
      cursor: default;
      background: transparent;
    }

    .fx-row[data-kind='section'] {
      position: sticky;
      top: 0;
      z-index: 1;
      height: 24px;
      line-height: 24px;
      padding-left: var(--oc-space-0-5);
      border-radius: 0;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .fx-row[data-kind='section']:hover {
      background: var(--oc-ground-titlerow);
    }

    .fx-guides {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 2px;
      width: calc((var(--fx-depth) - 1) * var(--fx-indent));
      background: repeating-linear-gradient(to right, transparent 0 5px, var(--oc-line-faint) 5px 6px, transparent 6px var(--fx-indent));
      pointer-events: none;
    }

    .fx-row[data-kind='section'] .fx-guides {
      display: none;
    }

    .fx-chev {
      flex: 0 0 12px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--oc-text-muted);
    }

    .fx-chev svg {
      fill: none;
      stroke: currentColor;
      stroke-width: 1.4;
      transition: transform var(--oc-motion-fast, 100ms) ease;
    }

    .fx-chev svg.fx-chev--open {
      transform: rotate(90deg);
    }

    @media (prefers-reduced-motion: reduce) {
      .fx-chev svg {
        transition: none;
      }
    }

    .fx-label {
      flex: 0 0 auto;
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label, 0.08em);
      text-transform: uppercase;
      color: var(--oc-orange);
    }

    .fx-name {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .fx-sub {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }

    .fx-sub--path {
      direction: rtl;
      text-align: left;
      flex: 0 1000 auto;
    }

    .fx-fill {
      flex: 1 1 0;
      min-width: 4px;
    }

    .fx-ro {
      flex: 0 0 auto;
      font-size: var(--oc-fs-micro, 10px);
      letter-spacing: var(--oc-tracking-label, 0.08em);
      color: var(--oc-text-muted);
    }

    .fx-mark {
      flex: 0 0 2ch;
      text-align: center;
      font-size: var(--oc-fs-label);
    }

    .fx-row--dim .fx-name {
      color: var(--oc-text-muted);
    }

    .fx-row[data-git-tone='green'] :is(.fx-name, .fx-mark) {
      color: var(--oc-green);
    }

    .fx-row[data-git-tone='yellow'] :is(.fx-name, .fx-mark) {
      color: var(--oc-yellow);
    }

    .fx-row[data-git-tone='coral'] :is(.fx-name, .fx-mark) {
      color: var(--oc-coral);
    }

    .fx-row[data-kind='group'] .fx-name,
    .fx-row[data-kind='more'] .fx-name {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label, 0.08em);
    }

    .fx-row[data-kind='note'] .fx-name {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }

    .fx-row[data-note='error'] .fx-name {
      color: var(--oc-coral);
    }
  }
</style>

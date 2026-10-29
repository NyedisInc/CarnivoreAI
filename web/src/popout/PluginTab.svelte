<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import { observeCell, sizeOf } from '../opscenter/engine/observe.svelte';
  import type { CellMeta } from '../opscenter/engine/types';
  import type { FrameHeader } from '../opscenter/shell/frame-header.svelte';
  import { useZonePane } from '../lib/zone-shell/zone-pane';

  let {
    widget,
    key,
    Cell,
    meta,
    label,
    head,
  }: {
    widget: string;
    key: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- a cell takes the cell contract's props (`opscenter/cells/registry.ts` types it the same way)
    Cell: Component<any>;
    meta: CellMeta;
    label: string;
    head: Snippet<[FrameHeader]>;
  } = $props();

  const header = useZonePane()!.header;
  header.drawn = true;
  $effect.pre(() => void (header.takesBars = !header.content));
  const box = $derived(sizeOf(key));
</script>

<section class="sw" data-popout-widget={widget} aria-label={label}>
  {@render head(header)}
  <div class="sw-body" {@attach observeCell(key)}>
    <Cell width={box.width} height={box.height} {meta} instance={widget} phone={false} limit={null} />
  </div>
</section>

<style>
  @layer components {
    .sw {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-width: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      container: oc-head / inline-size;
    }

    .sw-body {
      flex: 1 1 auto;
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }
  }
</style>

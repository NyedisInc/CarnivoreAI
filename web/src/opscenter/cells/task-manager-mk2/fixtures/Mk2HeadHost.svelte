<script lang="ts">
  import type { Component } from 'svelte';
  import { untrack } from 'svelte';
  import type { CellMeta } from '../../../engine/types';
  import { provideFrameHeader } from '../../../shell/frame-header.svelte';
  import WidgetHead from '../../../shell/WidgetHead.svelte';

  let { cell, props, meta, hostId = 'mk2-head' }: { cell: Component<any>; props: Record<string, unknown>; meta: CellMeta; hostId?: string } = $props();

  const header = untrack(() => provideFrameHeader(hostId));
  const Cell = untrack(() => cell);
</script>

<WidgetHead {meta} {header} title="TM Mark II" corner={null} onClose={null} />
<Cell {...props} />

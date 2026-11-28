<script lang="ts">
  import type { Component } from 'svelte';
  import { untrack } from 'svelte';
  import type { CellMeta } from '../../../sdk';
  import { provideFrameHeader } from '../../../sdk/widgets';
  import { WidgetHead } from '../../../sdk/widgets';

  let { cell, props, meta, hostId = 'mk2-head' }: { cell: Component<any>; props: Record<string, unknown>; meta: CellMeta; hostId?: string } = $props();

  const header = untrack(() => provideFrameHeader(hostId));
  const Cell = untrack(() => cell);
</script>

<WidgetHead {meta} {header} title="TM Mark II" corner={null} onClose={null} />
<Cell {...props} />

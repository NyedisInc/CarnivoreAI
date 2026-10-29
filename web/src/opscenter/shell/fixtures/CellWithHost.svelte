<script lang="ts">
  import type { Component } from 'svelte';
  import { provideFrameHeader } from '../frame-header.svelte';
  import { metaFor } from '../../engine/meta';
  import type { SlotId } from '../../engine/types';
  import type { CellProps } from '../../lib/cell';
  import type { SessionScope } from '../../widgets/session-scope';

  let { slot, cell, hostId, options = {}, onOption, scope = null, height = 600 }: {
    slot: SlotId;
    cell: Component<CellProps>;
    hostId: string;
    options?: Record<string, boolean | number | string>;
    onOption?: (key: string, value: boolean | number | string) => void;
    scope?: SessionScope | null;
    height?: number;
  } = $props();
  provideFrameHeader(hostId);
  const meta = $derived(metaFor(slot));
  const Cell = $derived(cell);
</script>
<Cell width={380} {height} {meta} instance={hostId} {options} {onOption} {scope} />

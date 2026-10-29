<script lang="ts">
  import CellFrame from '../CellFrame.svelte';
  import GroupCell from '../../cells/terminal-group/Cell.svelte';
  import { META, metaFor } from '../../engine/meta';
  import { terminalLayout } from '../../engine/layout.svelte';
  import type { SlotId } from '../../engine/types';
  let { slot, width = 1200 }: { slot: SlotId; width?: number } = $props();
</script>
<CellFrame meta={metaFor(slot, META)} instance={slot}
  widthState="wide" heightState="pane" store={terminalLayout}>
  {#snippet body()}
    <GroupCell {width} height={600} meta={metaFor(slot, META)} instance={slot} page="terminal" />
  {/snippet}
</CellFrame>

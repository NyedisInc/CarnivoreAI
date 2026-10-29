<script lang="ts">
  import CellFrame from '../../opscenter/shell/CellFrame.svelte';
  import HeadSortGroup from './HeadSortGroup.svelte';
  import { META, metaFor } from '../../opscenter/engine/meta';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';
  import type { SlotId } from '../../opscenter/engine/types';

  let {
    slot = 'notes',
    count = null,
    sortGroup = false,
  }: {
    slot?: SlotId;
    count?: number | null;
    sortGroup?: boolean;
  } = $props();
  let collapsed = $state(false);
</script>

<div class="sg-frame-host">
  <CellFrame
    meta={metaFor(slot, META)}
    instance={slot}
    widthState="wide"
    heightState="pane"
    store={terminalLayout}
    {count}
    {collapsed}
    onToggleCollapse={() => (collapsed = !collapsed)}
  >
    {#snippet body()}
      {#if sortGroup}<HeadSortGroup />{/if}
      <div class="sg-frame-body">
        <p>a component's body goes here. the frame owns the title row, the hairline under it, the count and the
          controls; the body owns nothing but its content.</p>
      </div>
    {/snippet}
  </CellFrame>
</div>

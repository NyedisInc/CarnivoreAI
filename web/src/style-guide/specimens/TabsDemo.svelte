<script lang="ts">
  import CellFrame from '../../opscenter/shell/CellFrame.svelte';
  import TabStripSlot from './TabStripSlot.svelte';
  import { META, metaFor } from '../../opscenter/engine/meta';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';

  let { variant = 'desktop' }: { variant?: 'desktop' | 'touch' | 'dragging' } = $props();

  const INSTANCE = 'terminal:@primary';
</script>

{#if variant === 'touch'}
  <div
    class="tw:flex tw:min-h-11 tw:min-w-0 tw:border-b tw:border-[var(--oc-line-chrome)] tw:bg-[var(--oc-ground-chrome)]"
    data-phone-tabs
  >
    <TabStripSlot variant="touch" />
  </div>
{:else}
  <div class="sg-frame-host sg-frame-host--tabs">
    <CellFrame
      meta={metaFor(INSTANCE, META)}
      instance={INSTANCE}
      widthState="wide"
      heightState="pane"
      store={terminalLayout}
    >
      {#snippet body()}
        <TabStripSlot {variant} />
      {/snippet}
    </CellFrame>
  </div>
{/if}

<script lang="ts">
  import CellFrame from '../CellFrame.svelte';
  import TerminalHead from '../../cells/terminal-live/TerminalHead.svelte';
  import { META, metaFor } from '../../engine/meta';
  import { terminalLayout } from '../../engine/layout.svelte';
  let { name = 'alpha' }: { name?: string } = $props();
</script>
<CellFrame meta={metaFor('terminal:@primary', META)} instance="terminal:@primary"
  widthState="wide" heightState="pane" store={terminalLayout}>
  {#snippet body()}
    
    <TerminalHead {name} hue="green" statusWord="working" sessionId="alpha"
      width={1200} slot="terminal:@primary" controller={null} />
    <p>terminal body</p>
  {/snippet}
</CellFrame>

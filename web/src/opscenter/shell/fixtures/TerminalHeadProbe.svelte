<script lang="ts">
  import TerminalHead from '../../cells/terminal-live/TerminalHead.svelte';

  const BAR_WIDTH = 378;
</script>

<div data-probe-terminal="">
  <TerminalHead hue="grey" sessionId="ses_1" controller={null} slot="terminal:row:7" width={BAR_WIDTH} name="alpha" agentFamily="claude" />
</div>

<script lang="ts">
  import AgentFamilyPill from '../../lib/launchpad/AgentFamilyPill.svelte';
  import WrapperPill from '../../lib/launchpad/WrapperPill.svelte';
</script>

<div class="sg-row">
  <AgentFamilyPill family="claude" source="wrapper" />
  <AgentFamilyPill family="codex" source="reserved_name" />
  <AgentFamilyPill family="claude" source="fingerprint" />
  <AgentFamilyPill family="codex" source="inferred_process" />
  <AgentFamilyPill family={null} source={null} />
  <WrapperPill label="summit" />
  <WrapperPill label="codex-yolo" />
</div>

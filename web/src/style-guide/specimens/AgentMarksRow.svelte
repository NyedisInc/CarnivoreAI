<script lang="ts">
  import SessionFace from '../../lib/sessions/SessionFace.svelte';
  import type { AgentMarkFacts } from '../../lib/sessions/agent-marks';

  const families: (string | null)[] = ['claude', 'codex', 'hermes', 'openclaw', 'local', 'shell', null];

  function facts(family: string | null): AgentMarkFacts {
    return {
      family,
      status: 'idle',
      unread: false,
      startupGate: null,
      statusSource: 'registry',
      activityHint: null,
      transport: null,
    };
  }
</script>

<ul class="sg-inline-list">
  {#each families as family (family ?? 'none')}
    <li class="sg-inline-item">
      <SessionFace facts={facts(family)} mark />
      <code>{family ?? 'null'}</code>
    </li>
  {/each}
</ul>

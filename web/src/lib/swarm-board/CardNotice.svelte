
<script lang="ts">
  import { cardNotice } from './card-actions.svelte';
</script>

{#if cardNotice.text}
  <p class="sbn" class:sbn--bad={!cardNotice.ok} role="status" data-swarm-card-said={cardNotice.ok ? 'ok' : 'error'}>{cardNotice.text}</p>
{/if}

<style>
  @layer components {
    .sbn {
      grid-column: 1 / -1;
      margin: 0;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
    }
    .sbn--bad {
      color: var(--oc-coral);
    }
  }
</style>

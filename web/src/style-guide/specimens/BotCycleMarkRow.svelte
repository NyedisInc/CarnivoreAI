<script lang="ts">
  import BotCycleMark from '../../lib/account-switch/BotCycleMark.svelte';

  const sizes = [14, 18, 24];
</script>

<ul class="sg-inline-list">
  {#each sizes as size (size)}
    <li class="sg-inline-item" style="color: var(--oc-text-muted)"><BotCycleMark {size} /><code>{size} off</code></li>
    <li class="sg-inline-item" style="color: var(--oc-violet)"><BotCycleMark {size} /><code>{size} on</code></li>
  {/each}
</ul>

<script lang="ts">
  import { useHeaderGroup } from '../frame-header.svelte';

  let firstOn = $state(true);
  useHeaderGroup(() => (firstOn ? first : null));
  useHeaderGroup(() => second);
</script>

{#snippet first()}
  <button type="button" data-probe-group="first">first</button>
{/snippet}

{#snippet second()}
  <button type="button" data-probe-group="second">second</button>
{/snippet}

<button type="button" data-probe-toggle="" onclick={() => (firstOn = !firstOn)}>toggle</button>

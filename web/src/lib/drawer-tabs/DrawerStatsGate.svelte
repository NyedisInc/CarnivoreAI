<script lang="ts">
  import DrawerStats from './DrawerStats.svelte';
  import { statsShown } from '../drawer/stats-visibility.svelte';
</script>

{#if statsShown() === true}
  <DrawerStats />
{/if}

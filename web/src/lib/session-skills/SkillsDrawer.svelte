<script lang="ts">
  /* session skills */
  import SessionSkillsPanel from './SessionSkillsPanel.svelte';
  import { setSkillsDrawer, skillsDrawerOpen } from './drawer.svelte';

  let { sessionId, slot, width }: { sessionId: string; slot: string; width: number } = $props();
</script>

{#if sessionId && skillsDrawerOpen(slot)}
  <SessionSkillsPanel {sessionId} {slot} full={width < 520} onClose={() => setSkillsDrawer(slot, false)} />
{/if}

<script lang="ts">
  /* the icon that opens the one menu */
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import NotesTab from './NotesTab.svelte';
  import { NOTES_ONLY, rightDrawerZone } from '../right-drawer/zone.svelte';

  let { onClose, onComponent, canComponent }: {
    onClose: () => void;
    onComponent: () => void;
    canComponent: () => boolean;
  } = $props();
</script>

{#snippet notesTab()}
  <NotesTab {onClose} {onComponent} {canComponent} />
{/snippet}

<ZoneShell zone={rightDrawerZone} tab={notesTab} mount="active" only={NOTES_ONLY} />

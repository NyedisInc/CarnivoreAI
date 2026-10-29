<script lang="ts">
  import Glyph from '../../../lib/Glyph.svelte';
  import { sizeMasterRole, toggleSizeMaster } from '../../api/size-master.svelte';
  import { t } from '../../../lib/i18n/index.svelte';

  let { sessionId }: { sessionId: string } = $props();
  let busy = $state(false);

  const role = $derived(sizeMasterRole(sessionId));
  const label = $derived(t(`terminal.size_master.${role}`));

  async function toggle(): Promise<void> {
    if (busy || !sessionId) return;
    busy = true;
    try { await toggleSizeMaster(sessionId); } finally { busy = false; }
  }
</script>

<button type="button" class="size-crown" data-tool="size-master" data-size-master={role}
  title={label} aria-label={label} aria-pressed={role === 'master'}
  disabled={!sessionId} onclick={toggle}><Glyph name="crown" size={15} /></button>

<style>
  @layer components {
    .size-crown { display:flex; align-items:center; justify-content:center; width:26px; height:var(--cell-tool-h, 26px); padding:0; border:1px solid transparent; border-radius:3px; background:transparent; color:var(--oc-text-dim); cursor:pointer; }

    .size-crown:hover, .size-crown:focus-visible { border-color:var(--oc-orange); background:var(--oc-ground-hover); }

    .size-crown:disabled { opacity:.4; cursor:default; }

    .size-crown[data-size-master='watcher'] { color:var(--oc-yellow); opacity:.7; }

    .size-crown[data-size-master='master'] { color:var(--oc-yellow-bright); }

    .size-crown[data-size-master='master'] :global(svg) { fill:currentColor; }
  }
</style>

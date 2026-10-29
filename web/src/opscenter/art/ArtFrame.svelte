<script lang="ts">
  import { onMount } from 'svelte';
  import { loadArtDensity } from './density.svelte';
  onMount(() => {
    loadArtDensity();
  });
</script>
<div class="oc-ascii-frame" aria-hidden="true">
  <pre class="oc-ascii-rail">░▒▓╞═══════════════╪───────── · ·</pre>
  <pre class="oc-ascii-joint">· · ─────────╪═══════════════╡▓▒░</pre>
  <pre class="oc-ascii-spill">┆
╎
░
▒
▓
╎
┆</pre>
</div>

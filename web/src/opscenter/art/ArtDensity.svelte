<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { artDensity, DENSITIES, loadArtDensity, setArtDensity } from './density.svelte';
  onMount(loadArtDensity);
</script>
<label class="oc-art-density">{t('art.density.label')}
  <select value={artDensity.value} onchange={(event) => setArtDensity(event.currentTarget.value)}>
    {#each DENSITIES as density}<option value={density}>{density}</option>{/each}
  </select>
</label>
<style>
  @layer components {
    .oc-art-density { display:flex; align-items:center; flex-wrap:wrap; gap:var(--oc-space-2); font-size:var(--oc-fs-label); color:var(--oc-text-secondary); }

    select { color:var(--oc-text-primary); background:var(--oc-ground-field); border:1px solid var(--oc-line-panel); border-radius:var(--oc-radius-sm); font:inherit; min-height:32px; padding:var(--oc-space-1) var(--oc-space-2); }

    @media (pointer:coarse) { select { min-height:44px; }
  }
  }
</style>

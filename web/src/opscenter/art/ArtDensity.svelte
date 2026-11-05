<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { Select } from '../../lib/base';
  import { artDensity, DENSITIES, loadArtDensity, setArtDensity } from './density.svelte';
  onMount(loadArtDensity);
  const OPTIONS = DENSITIES.map((density) => ({ value: density, label: density }));
</script>
<label class="oc-art-density">{t('art.density.label')}
  <Select value={artDensity.value} options={OPTIONS} onchange={(event) => setArtDensity(event.currentTarget.value)} />
</label>
<style>
  @layer components {
    .oc-art-density { display:flex; align-items:center; flex-wrap:wrap; gap:var(--oc-space-2); font-size:var(--oc-fs-label); color:var(--oc-text-secondary); }

  }
</style>


<script lang="ts">
  import { onMount } from 'svelte';
  import ModalShell from '../../launchpad/ModalShell.svelte';
  import type { Translate } from '../../sessions/types';
  import * as api from './pack-skills-api';

  import { providerMark } from '../../sessions/agent-marks';

  let { families, name, placedBy = '', onClose, t }: { families: string[]; name: string; placedBy?: string; onClose: () => void; t: Translate } = $props();
  let details = $state<api.SkillDetail[]>([]);
  let error = $state('');

  onMount(() => {
    for (const family of families) {
      api.getDetail(family, name).then((d) => (details = [...details, d].sort((a, b) => families.indexOf(a.family) - families.indexOf(b.family))), (e: unknown) => (error = e instanceof Error ? e.message : String(e)));
    }
  });
</script>

<ModalShell title={name} onCancel={onClose} overlayClass="lsk-sheet-overlay">
  <div class="lsk-sheet" data-pks-detail>
    {#if error}<p class="lsk-line lsk-line--error" role="alert">{error}</p>{/if}
    {#if placedBy}<p class="lsk-line" data-pks-detail-placed-by>{t('skills.pack.detail.placed_by', { label: placedBy })}</p>{/if}
    {#each details as detail (detail.family)}
      {@const mark = providerMark(detail.family, 14)}
      <p class="lsk-sheet__heading" data-pks-detail-family={detail.family}><span class="pks-fam" role="img" aria-label={mark.label}>{@html mark.svg}</span>{detail.family}</p>
      {#each detail.computers ?? [] as c (c.id)}
        <p class="lsk-line" data-pks-detail-computer={c.id}>{c.label}: {c.digests.length ? c.digests.map((d) => d.slice(0, 12)).join(', ') : t('skills.pack.detail.none')}{c.from_warez ? ` (${t('skills.pack.detail.from_warez')})` : ''}</p>
      {/each}
      {#if detail.here}
        <p class="lsk-sheet__heading">{t('skills.pack.detail.files')}</p>
        <ul class="lsk-files">{#each detail.here.files as f (f.path)}<li>{f.path} · {f.size} · {f.sha256.slice(0, 12)}</li>{/each}</ul>
        {#if detail.here.scripts.length}<p class="lsk-line lsk-line--warn">{t('skills.pack.sheet.scripts', { name })}</p>{/if}
      {/if}
    {/each}
    {#if details[0]}<p class="lsk-line">{t('skills.pack.detail.local', { names: details[0].machine_local.join(', ') })}</p>{/if}
  </div>
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" onclick={onClose}>{t('skills.command.sheet.close')}</button>
  {/snippet}
</ModalShell>

<script lang="ts">
  /* could not */
  import { t } from '../sdk';
  import type { CaptureOutcome } from './lab-model';

  interface Props {
    items: CaptureOutcome[];
    running: boolean;
  }

  const { items, running }: Props = $props();

  let open = $state(false);
  $effect(() => {
    if (items[0] && !items[0].ok) open = true;
  });
</script>

<details class="dwl-results" bind:open>
  <summary class="dwl-label">{t('cplug.devwidgetlab.results.title')} ({items.length})</summary>
  {#if running}<p class="dwl-note">{t('cplug.devwidgetlab.capture.running')}</p>{/if}
  {#if items.length === 0 && !running}
    <p class="dwl-note">{t('cplug.devwidgetlab.results.empty')}</p>
  {/if}
  <ol class="dwl-result-list">
    {#each items as item}
      <li class="dwl-result" data-ok={item.ok ? 'yes' : 'no'}>
        <p class="dwl-result-head">
          <span class="dwl-chip" class:dwl-chip--off={!item.ok}>{item.ok ? t('cplug.devwidgetlab.results.ok') : t('cplug.devwidgetlab.results.failed')}</span>
          <span>{item.widget ?? ''} {item.host ?? ''} {item.size?.name ?? ''} {item.theme ?? ''} {item.state ?? ''}</span>
        </p>
        {#each item.failures as failure}<p class="dwl-note dwl-note--error">{failure}</p>{/each}
        {#if item.png?.pixels}
          <p class="dwl-path"><span class="dwl-label">{t('cplug.devwidgetlab.results.png')}</span> <code>{item.png.path}</code> ({item.png.pixels[0]} x {item.png.pixels[1]})</p>
        {/if}
        {#if item.metadata}<p class="dwl-path"><span class="dwl-label">{t('cplug.devwidgetlab.results.metadata')}</span> <code>{item.metadata}</code></p>{/if}
      </li>
    {/each}
  </ol>
</details>

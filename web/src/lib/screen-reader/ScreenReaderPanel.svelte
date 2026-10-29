<script lang="ts">
  import { onDestroy } from 'svelte';
  import Radio from '../base/Radio.svelte';
  import RadioGroup from '../base/RadioGroup.svelte';
  import { t } from '../i18n/index.svelte';
  import { SCREEN_READER_MODES, followScreenReaderMode, readScreenReaderMode, saveScreenReaderMode, type ScreenReaderMode } from './screen-reader';

  let mode = $state<ScreenReaderMode>(readScreenReaderMode());
  let saving = $state(false);
  let error = $state<string | null>(null);

  const stop = followScreenReaderMode((next) => {
    mode = next;
  });
  onDestroy(stop);

  async function pick(next: ScreenReaderMode): Promise<void> {
    const before = readScreenReaderMode();
    mode = next;
    if (next === before) return;
    saving = true;
    const why = await saveScreenReaderMode(next);
    saving = false;
    if (why) {
      mode = before;
      error = t('screen_reader.error.save', { reason: why === 'unavailable' ? t('screen_reader.unavailable') : why });
    } else {
      error = null;
    }
  }
</script>

<div class="screen-reader-panel" data-settings-section="screen-reader">
  <RadioGroup label={t('screen_reader.title')} disabled={saving} bind:value={() => mode, (next) => void pick(next as ScreenReaderMode)}>
    {#each SCREEN_READER_MODES as choice (choice)}
      <Radio value={choice} label={t(`screen_reader.${choice}`)} hint={t(`screen_reader.${choice}_hint`)} data-screen-reader={choice} />
    {/each}
  </RadioGroup>
  {#if saving}
    <p class="settings-field-hint" role="status">{t('screen_reader.saving')}</p>
  {/if}
  {#if error}
    <p class="settings-field-hint screen-reader-error" role="alert">{error}</p>
  {/if}
</div>

<style>
  .screen-reader-error {
    color: var(--oc-coral);
  }
</style>

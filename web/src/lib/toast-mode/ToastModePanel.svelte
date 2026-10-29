<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { TOAST_MODES, followToastMode, readToastMode, saveToastMode, type ToastMode } from './toast-mode';

  let mode = $state<ToastMode>(readToastMode());
  let saving = $state(false);
  let error = $state<string | null>(null);

  const stop = followToastMode((next) => {
    mode = next;
  });
  onDestroy(stop);

  async function pick(next: ToastMode): Promise<void> {
    const before = readToastMode();
    mode = next;
    if (next === before) return;
    saving = true;
    const why = await saveToastMode(next);
    saving = false;
    if (why) {
      mode = before;
      const reason = why === 'unavailable' ? t('toast.mode.unavailable') : why;
      error = t('toast.mode.error.save', { reason });
    } else {
      error = null;
    }
  }
</script>

<section class="settings-section toast-mode-panel" data-settings-section="toast-mode">
  <h3 class="settings-section-title">{t('toast.mode.title')}</h3>
  <div class="settings-section-description">{t('toast.mode.hint')}</div>
  <div class="restart-picker__options toast-mode-options" role="radiogroup" aria-label={t('toast.mode.title')}>
    {#each TOAST_MODES as choice (choice)}
      <label class="restart-picker__option toast-mode-option" for={`toast-mode-${choice}`}>
        <input
          type="radio"
          name="toast-mode"
          id={`toast-mode-${choice}`}
          value={choice}
          data-toast-mode={choice}
          checked={mode === choice}
          disabled={saving}
          onchange={() => void pick(choice)}
        />
        <span class="restart-picker__title toast-mode-choice">
          <span class="toast-mode-name">{t(`toast.mode.${choice}`)}</span>
          <span class="settings-field-hint">{t(`toast.mode.${choice}_hint`)}</span>
        </span>
      </label>
    {/each}
  </div>
  {#if saving}
    <p class="settings-field-hint" role="status">{t('toast.mode.saving')}</p>
  {/if}
  {#if error}
    <p class="settings-field-hint toast-mode-error" role="alert">{error}</p>
  {/if}
</section>

<style>
  .toast-mode-options {
    max-height: none;
    margin-top: 8px;
  }

  .toast-mode-option {
    align-items: flex-start;
    padding: 8px 10px;
  }

  .toast-mode-option input[type='radio'] {
    margin-top: 2px;
  }

  .toast-mode-choice {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .toast-mode-name {
    color: var(--oc-text-primary);
  }

  .toast-mode-error {
    color: var(--oc-coral);
  }
</style>


<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import type { createMic } from './controller.svelte';

  let { mic }: { mic: ReturnType<typeof createMic> } = $props();
  const s = $derived(mic.state);
</script>

{#if s.phase !== 'idle'}
  <div class="pmic" role="region" aria-label={t('phone.mic.label')} data-phase={s.phase}>
    {#if s.phase === 'message'}
      <p class="pmic__text pmic__text--note" role="status">{t(`phone.mic.reason.${s.reason}`)}</p>
      <div class="pmic__row">
        <Button onclick={mic.dismiss}>{t('phone.mic.ok')}</Button>
      </div>
    {:else}
      <div class="pmic__title">
        <span class="pmic__dot" aria-hidden="true"></span>
        <span class="pmic__label">{s.phase === 'working' ? t('phone.mic.working') : s.live ? t('phone.mic.listening') : t('phone.mic.recording')}</span>
      </div>
      <p class="pmic__text" aria-live="polite">{s.transcript || (s.live ? t('phone.mic.speak_now') : t('phone.mic.recording_hint'))}</p>
      <div class="pmic__row">
        <Button onclick={mic.cancel}>{t('phone.mic.cancel')}</Button>
        <Button variant="confirm" disabled={s.phase === 'working'} onclick={mic.done}>{t('phone.mic.done')}</Button>
      </div>
    {/if}
  </div>
{/if}

<style>
  .pmic {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 2000;
    padding: var(--oc-space-2) max(var(--oc-space-3), env(safe-area-inset-right, 0px)) calc(var(--oc-space-3) + env(safe-area-inset-bottom, 0px)) max(var(--oc-space-3), env(safe-area-inset-left, 0px));
    background: var(--oc-ground-titlerow);
    box-shadow: 0 -1px 0 var(--oc-line-frame);
    font-family: var(--oc-font);
    color: var(--oc-text-primary);
  }
  .pmic__title { display: flex; align-items: center; gap: var(--oc-space-2); height: var(--oc-space-5); }
  .pmic__label { font-size: var(--oc-fs-label); letter-spacing: 0.12em; text-transform: uppercase; color: var(--oc-orange); }
  .pmic__dot { width: var(--oc-space-2); height: var(--oc-space-2); background: var(--oc-green); }
  .pmic__text {
    margin: var(--oc-space-1) 0 var(--oc-space-2);
    min-height: 3.6em;
    max-height: 30vh;
    overflow-y: auto;
    font-size: var(--oc-fs-card-name);
    line-height: 1.3;
    overflow-wrap: anywhere;
    box-shadow: 0 1px 0 var(--oc-line-rule);
    padding-bottom: var(--oc-space-2);
  }
  .pmic__text--note { min-height: 0; color: var(--oc-text-secondary); }
  .pmic__row { display: flex; gap: var(--oc-space-2); justify-content: flex-end; }
  .pmic__row :global([data-btn]) { min-width: 96px; min-height: 40px; }
</style>

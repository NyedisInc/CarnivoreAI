<script lang="ts">
  import { t } from '../sdk';

  interface Props {
    count: number;
    running: { done: number; total: number } | null;
    last: { ok: number; failed: number } | null;
    available: boolean;
    reason: string;
    oncapture: () => void;
  }

  const { count, running, last, available, reason, oncapture }: Props = $props();
</script>

<div class="dwl-foot">
  <button type="button" class="oc-btn oc-btn--confirm dwl-foot-key" disabled={!available || running !== null || count === 0} onclick={oncapture}>
    {running ? t('cplug.devwidgetlab.capture.progress', { done: running.done, total: running.total }) : count === 1 ? t('cplug.devwidgetlab.capture.frame') : t('cplug.devwidgetlab.capture.frames', { count })}
  </button>
  {#if !available}
    <p class="dwl-note">{t(`cplug.devwidgetlab.capture.unavailable.${reason || 'unknown'}`)}</p>
  {:else if last}
    <p class="dwl-note" class:dwl-note--ok={last.failed === 0} class:dwl-note--error={last.failed > 0}>
      {last.failed === 0 ? t('cplug.devwidgetlab.capture.done', { ok: last.ok }) : t('cplug.devwidgetlab.capture.some_failed', { ok: last.ok, failed: last.failed })}
    </p>
  {/if}
</div>

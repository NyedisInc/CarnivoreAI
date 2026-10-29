<script lang="ts">
  import { t } from '../sdk';
  import type { DraftSource } from './drafts-model';

  interface Props {
    available: boolean;
    canRevise: boolean;
    source: DraftSource;
    onnew: () => void;
    onrevise: () => void;
  }

  const { available, canRevise, source, onnew, onrevise }: Props = $props();
</script>

<div class="dwl-actions">
  <span class="dwl-label">{t('cplug.devwidgetlab.drafts.title')}</span>
  <div class="dwl-seg">
    <button type="button" class="oc-btn oc-btn--sm" data-draft-new disabled={!available} onclick={onnew}>{t('cplug.devwidgetlab.drafts.new')}</button>
    <button type="button" class="oc-btn oc-btn--sm" data-draft-revise disabled={!available || !canRevise} onclick={onrevise}>{t('cplug.devwidgetlab.drafts.revise')}</button>
  </div>
</div>
{#if !available}<p class="dwl-note dwl-actions-note">{t('cplug.devwidgetlab.drafts.no_checkout')}</p>{/if}
{#if source.setting !== '' && source.problems.length > 0}
  <p class="dwl-note dwl-note--error">{t('cplug.devwidgetlab.drafts.source.broken', { path: source.setting, problems: source.problems.join('; ') })}</p>
{/if}


<script lang="ts">
  import ModalShell from '../../launchpad/ModalShell.svelte';
  import type { Translate } from '../../sessions/types';
  import * as api from './pack-skills-api';

  let { from, family, name, alpha, onDone, onClose, t }: { from: { id: string; label: string }; family: string; name: string; alpha: string; onDone: () => Promise<void>; onClose: () => void; t: Translate } = $props();

  let plan = $state<api.TakePreview | null>(null);
  let busy = $state<'' | 'check' | 'write'>('');
  let notice = $state('');

  const KNOWN = ['needs_update', 'offline', 'computer_one_way', 'catalog_skill', 'skill_held', 'skill_is_link', 'not_found', 'bad_bundle', 'bad_answer', 'unreachable'];

  function say(error: unknown): void {
    plan = null;
    const code = api.refusalCode(error);
    if (code === 'plan_stale') notice = t('skills.pack.sheet.stale');
    else if (code && KNOWN.includes(code)) notice = t(`skills.pack.take_refused.${code}`, { computer: from.label });
    else notice = t('skills.pack.sheet.failed', { reason: error instanceof Error ? error.message : String(error) });
  }

  async function check(): Promise<void> {
    busy = 'check';
    notice = '';
    plan = null;
    try {
      plan = await api.takeCopy(from.id, family, name, true);
    } catch (error) {
      say(error);
    } finally {
      busy = '';
    }
  }

  async function confirm(): Promise<void> {
    if (!plan || busy) return;
    busy = 'write';
    try {
      const done = await api.takeCopy(from.id, family, name, false, plan.plan_token);
      await onDone();
      if (done.ok) onClose();
      else {
        plan = null;
        notice = t('skills.pack.take_partial', { reasons: done.conflicts.join(', ') });
      }
    } catch (error) {
      say(error);
    } finally {
      busy = '';
    }
  }

  $effect(() => {
    void check();
  });
</script>

<ModalShell title={t('skills.pack.take_title', { name, computer: from.label })} dismissable={!busy} onCancel={onClose} overlayClass="lsk-sheet-overlay">
  <div class="lsk-sheet" data-pks-take-sheet>
    {#if busy === 'check'}<p class="lsk-line" role="status">{t('skills.pack.take_checking')}</p>{/if}
    {#if plan}
      <div class="lsk-plan" data-pks-take-plan>
        <p class="lsk-sheet__heading">{t('skills.command.sheet.plan_heading')}</p>
        <p class="lsk-line">{t('skills.command.sheet.size', { files: plan.files, bytes: plan.bytes })}</p>
        {#if plan.scripts.length}
          <p class="lsk-line lsk-line--warn" data-pks-scripts>{t('skills.pack.sheet.scripts', { name })}</p>
          <ul class="lsk-files">{#each plan.scripts as file}<li>{file}</li>{/each}</ul>
        {/if}
        <p class="lsk-line" data-pks-take-here={plan.here}>{t(`skills.pack.take_here_${plan.here}`, { alpha })}</p>
      </div>
    {/if}
    {#if notice}<p class="lsk-line lsk-line--warn" role="alert" data-pks-notice>{notice}</p>{/if}
  </div>
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" disabled={busy === 'write'} data-pks-cancel onclick={onClose}>{t('skills.command.sheet.cancel')}</button>
    {#if plan}
      <button type="button" class="modal-btn modal-btn-confirm" data-pks-take-confirm disabled={busy === 'write' || plan.here === 'same'} onclick={() => void confirm()}>{busy === 'write' ? t('skills.pack.take_taking') : t('skills.pack.take_confirm')}</button>
    {/if}
  {/snippet}
</ModalShell>

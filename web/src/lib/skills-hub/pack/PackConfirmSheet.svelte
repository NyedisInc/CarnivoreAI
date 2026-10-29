
<script lang="ts">
  import Radio from '../../base/Radio.svelte';
  import RadioGroup from '../../base/RadioGroup.svelte';
  import ModalShell from '../../launchpad/ModalShell.svelte';
  import type { Translate } from '../../sessions/types';
  import * as api from './pack-skills-api';

  let { call, onDone, onClose, t }: { call: api.PlanCall; onDone: () => Promise<void>; onClose: () => void; t: Translate } = $props();

  let removeElsewhere = $state(false);
  let plan = $state<api.Preview | null>(null);
  let busy = $state<'' | 'check' | 'write'>('');
  let notice = $state('');

  const effective = $derived<api.PlanCall>(call.kind === 'skill' ? { ...call, removeElsewhere: !call.synced && removeElsewhere } : call);
  const turningOff = $derived(call.kind === 'mode' ? call.mode === 'off' : !call.synced);
  const title = $derived(call.kind === 'mode' ? t(`skills.pack.sheet.title_mode_${call.mode}`) : t(call.synced ? 'skills.pack.sheet.title_on' : 'skills.pack.sheet.title_off', { name: call.name }));

  function say(error: unknown): void {
    plan = null;
    notice = api.refusalCode(error) === 'plan_stale' ? t('skills.pack.sheet.stale') : t('skills.pack.sheet.failed', { reason: error instanceof Error ? error.message : String(error) });
  }

  async function check(): Promise<void> {
    busy = 'check';
    notice = '';
    plan = null;
    try {
      plan = await api.runPlan(effective, true);
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
      await api.runPlan(effective, false, plan.plan_token);
      await onDone();
      onClose();
    } catch (error) {
      say(error);
    } finally {
      busy = '';
    }
  }

  $effect(() => {
    void effective;
    void check();
  });
</script>

<ModalShell {title} dismissable={!busy} onCancel={onClose} overlayClass="lsk-sheet-overlay">
  <div class="lsk-sheet" data-pks-sheet>
    {#if turningOff && call.kind === 'skill'}
      <RadioGroup label={title} bind:value={() => (removeElsewhere ? 'remove' : 'keep'), (next) => (removeElsewhere = next === 'remove')}>
        <Radio value="keep" label={t('skills.pack.sheet.keep')} data-pks-keep />
        <Radio value="remove" label={t('skills.pack.sheet.remove')} data-pks-remove />
      </RadioGroup>
    {/if}
    {#if busy === 'check'}<p class="lsk-line" role="status">{t('skills.pack.sheet.checking')}</p>{/if}
    {#if plan}
      <div class="lsk-plan" data-pks-plan>
        <p class="lsk-sheet__heading">{t('skills.command.sheet.plan_heading')}</p>
        <p class="lsk-line">{t('skills.command.sheet.size', { files: plan.total_files, bytes: plan.total_bytes })}</p>
        {#each plan.skills.filter((s) => s.scripts.length) as s (s.family + s.name)}
          <p class="lsk-line lsk-line--warn" data-pks-scripts>{t('skills.pack.sheet.scripts', { name: s.name })}</p>
          <ul class="lsk-files">{#each s.scripts as file}<li>{file}</li>{/each}</ul>
        {/each}
        <ul class="lsk-results">
          {#each plan.computers as c (c.id)}
            <li class="lsk-result" data-pks-computer={c.id}>
              <span class="lsk-result__label">{c.label}</span>
              {#if c.state !== 'ok'}
                <span class="lsk-result__status">{c.state}</span>
              {:else}
                <span class="lsk-result__status">{t('skills.pack.sheet.counts', { add: c.add, replace: c.replace, same: c.same, conflict: c.conflict })}</span>
                {#each Object.entries(c.skills) as [skill, word] (skill)}<span class="lsk-line">{skill}: {word}</span>{/each}
              {/if}
            </li>
          {/each}
        </ul>
        {#if plan.others}<p class="lsk-line lsk-col__sub" data-pks-others>{t('skills.pack.sheet.others', { count: plan.others })}</p>{/if}
      </div>
    {/if}
    {#if notice}<p class="lsk-line lsk-line--warn" role="alert" data-pks-notice>{notice}</p>{/if}
  </div>
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" disabled={busy === 'write'} data-pks-cancel onclick={onClose}>{t('skills.command.sheet.cancel')}</button>
    {#if plan}
      <button
        type="button"
        class="modal-btn {turningOff && removeElsewhere ? 'modal-btn-danger' : 'modal-btn-confirm'}"
        data-pks-confirm
        disabled={busy === 'write'}
        onclick={() => void confirm()}>{busy === 'write' ? t('skills.pack.sheet.applying') : t('skills.pack.sheet.confirm')}</button
      >
    {/if}
  {/snippet}
</ModalShell>

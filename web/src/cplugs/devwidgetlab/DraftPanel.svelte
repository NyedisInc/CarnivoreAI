<script lang="ts">
  import { t } from '../sdk';
  import { buildFailure, stateWord, type DraftSummary } from './drafts-model';
  import type { CompareMode } from './lab-selection';

  interface Props {
    draft: DraftSummary;
    compare: CompareMode;
    busy: boolean;
    error: string;
    onbuild: () => void;
    onhand: () => void;
    ondiscard: () => void;
    oncompare: (mode: CompareMode) => void;
  }

  const { draft, compare, busy, error, onbuild, onhand, ondiscard, oncompare }: Props = $props();

  let confirming = $state(false);
  const failure = $derived(buildFailure(draft));
  const building = $derived(draft.state === 'building');
</script>

<div class="dwl-draft" data-draft={draft.slug}>
  <p class="dwl-hint">{draft.kind === 'new' ? t('cplug.devwidgetlab.drafts.kind_new') : t('cplug.devwidgetlab.drafts.kind_revision', { widget: draft.widget })}</p>
  <p class="dwl-hint">{t('cplug.devwidgetlab.drafts.folder', { slug: draft.slug, count: draft.files.length })}</p>
  {#if draft.stale}<p class="dwl-note">{t('cplug.devwidgetlab.drafts.stale')}</p>{/if}
  {#if draft.session}<p class="dwl-hint">{t('cplug.devwidgetlab.drafts.session', { id: draft.session })}</p>{/if}

  <div class="dwl-seg">
    <button type="button" class="oc-btn oc-btn--sm" data-draft-build disabled={busy || building} onclick={onbuild}>
      {draft.build.state === 'built' ? t('cplug.devwidgetlab.drafts.rebuild') : t('cplug.devwidgetlab.drafts.build')}</button>
    <button type="button" class="oc-btn oc-btn--sm" data-draft-hand disabled={busy} onclick={onhand}>
      {draft.session ? t('cplug.devwidgetlab.drafts.hand_again') : t('cplug.devwidgetlab.drafts.hand')}</button>
  </div>
  <p class="dwl-hint" data-state={stateWord(draft)}>{t(`cplug.devwidgetlab.drafts.state.${stateWord(draft)}`)}{draft.build.built_at ? ` / ${draft.build.built_at}` : ''}</p>
  {#if failure}<p class="dwl-note dwl-note--error">{failure}{#if draft.build.log} <span class="dwl-path">{draft.build.log}</span>{/if}</p>{/if}

  {#if draft.kind === 'revision'}
    <div class="dwl-row" role="group" aria-label={t('cplug.devwidgetlab.drafts.compare')}>
      <span class="dwl-label">{t('cplug.devwidgetlab.drafts.compare')}</span>
      <div class="dwl-seg">
        {#each ['side', 'draft'] as const as one (one)}
          <button type="button" class="oc-btn oc-btn--sm" aria-pressed={compare === one} data-on={compare === one ? 'yes' : 'no'}
            onclick={() => oncompare(one)}>{t(`cplug.devwidgetlab.drafts.compare.${one}`)}</button>
        {/each}
      </div>
    </div>
  {/if}

  <p class="dwl-hint">{t('cplug.devwidgetlab.drafts.ships')}</p>
  {#if error}<p class="dwl-note dwl-note--error">{error}</p>{/if}

  {#if confirming}
    <p class="dwl-note">{t('cplug.devwidgetlab.drafts.discard_ask')}</p>
    <div class="dwl-seg">
      <button type="button" class="oc-btn oc-btn--sm oc-btn--danger" data-draft-discard-yes disabled={busy} onclick={() => { confirming = false; ondiscard(); }}>{t('cplug.devwidgetlab.drafts.discard_yes')}</button>
      <button type="button" class="oc-btn oc-btn--sm" onclick={() => (confirming = false)}>{t('cplug.devwidgetlab.drafts.cancel')}</button>
    </div>
  {:else}
    <button type="button" class="oc-btn oc-btn--sm oc-btn--danger" data-draft-discard disabled={busy} onclick={() => (confirming = true)}>{t('cplug.devwidgetlab.drafts.discard')}</button>
  {/if}
</div>

<script lang="ts">
  import { t } from '../sdk';
  import { Button, Segmented } from '../sdk/ui';
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
    <Button size="sm" data-draft-build disabled={busy || building} onclick={onbuild}>
      {draft.build.state === 'built' ? t('cplug.devwidgetlab.drafts.rebuild') : t('cplug.devwidgetlab.drafts.build')}</Button>
    <Button size="sm" data-draft-hand disabled={busy} onclick={onhand}>
      {draft.session ? t('cplug.devwidgetlab.drafts.hand_again') : t('cplug.devwidgetlab.drafts.hand')}</Button>
  </div>
  <p class="dwl-hint" data-state={stateWord(draft)}>{t(`cplug.devwidgetlab.drafts.state.${stateWord(draft)}`)}{draft.build.built_at ? ` / ${draft.build.built_at}` : ''}</p>
  {#if failure}<p class="dwl-note dwl-note--error">{failure}{#if draft.build.log} <span class="dwl-path">{draft.build.log}</span>{/if}</p>{/if}

  {#if draft.kind === 'revision'}
    <div class="dwl-row">
      <span class="dwl-label">{t('cplug.devwidgetlab.drafts.compare')}</span>
      <Segmented label={t('cplug.devwidgetlab.drafts.compare')} value={compare} onchange={(next) => oncompare(next as CompareMode)}
        options={(['side', 'draft'] as const).map((one) => ({ value: one, label: t(`cplug.devwidgetlab.drafts.compare.${one}`), attrs: { 'data-compare': one } }))} />
    </div>
  {/if}

  <p class="dwl-hint">{t('cplug.devwidgetlab.drafts.ships')}</p>
  {#if error}<p class="dwl-note dwl-note--error">{error}</p>{/if}

  {#if confirming}
    <p class="dwl-note">{t('cplug.devwidgetlab.drafts.discard_ask')}</p>
    <div class="dwl-seg">
      <Button variant="danger" size="sm" data-draft-discard-yes disabled={busy} onclick={() => { confirming = false; ondiscard(); }}>{t('cplug.devwidgetlab.drafts.discard_yes')}</Button>
      <Button size="sm" onclick={() => (confirming = false)}>{t('cplug.devwidgetlab.drafts.cancel')}</Button>
    </div>
  {:else}
    <Button variant="danger" size="sm" data-draft-discard disabled={busy} onclick={() => (confirming = true)}>{t('cplug.devwidgetlab.drafts.discard')}</Button>
  {/if}
</div>

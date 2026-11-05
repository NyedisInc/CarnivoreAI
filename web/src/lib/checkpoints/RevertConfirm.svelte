<script lang="ts">
  import { Button, IconButton } from '../base';
  import { t } from '../i18n/index.svelte';
  import ModalShell from '../dialog-frame/ModalShell.svelte';
  import { fetchRevertPreview, revertToCheckpoint, turnClock, type Checkpoint, type RevertDone, type RevertPreview } from './api';

  interface Props {
    rowId: number;
    checkpoint: Checkpoint;
    close: (value: RevertDone | null) => void;
  }

  const { rowId, checkpoint, close }: Props = $props();

  let preview = $state<RevertPreview | null>(null);
  let failed = $state('');
  let busy = $state(false);

  $effect(() => {
    let live = true;
    fetchRevertPreview(rowId, checkpoint.id).then(
      (p) => { if (live) preview = p; },
      (cause) => { if (live) failed = cause instanceof Error ? cause.message : t('checkpoints.revert.unknown'); },
    );
    return () => { live = false; };
  });

  const nothing = $derived(!!preview && preview.change.length + preview.create.length + preview.delete.length === 0);
  const blocked = $derived(!preview || preview.blocked_by.length > 0 || nothing);
  const groups = $derived<Array<[string, string[]]>>(preview
    ? [['change', preview.change], ['create', preview.create], ['delete', preview.delete]]
    : []);

  async function go(): Promise<void> {
    if (busy || blocked || !preview) return;
    busy = true;
    failed = '';
    try {
      close(await revertToCheckpoint(rowId, checkpoint.id, preview.fingerprint));
    } catch (cause) {
      failed = cause instanceof Error ? cause.message : t('checkpoints.revert.unknown');
    } finally {
      busy = false;
    }
  }

  const title = $derived(t(checkpoint.kind === 'safety' ? 'checkpoints.revert.title_safety' : 'checkpoints.revert.title',
    { time: turnClock(checkpoint.created_at) }));
</script>

<ModalShell {title} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)}>
  {#snippet head()}
    <div class="text-prompt-modal__head">
      <span class="text-prompt-modal__verb">{title}</span>
      <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close onclick={() => close(null)} />
    </div>
  {/snippet}
  <p class="modal-description">{t('checkpoints.revert.body')}</p>
  {#if !preview && !failed}
    <p class="modal-description" role="status" data-revert-loading="">{t('checkpoints.revert.loading')}</p>
  {/if}
  {#if preview}
    {#if preview.blocked_by.length > 0}
      <div class="rvc-blocked" role="alert" data-revert-blocked="">
        <span class="rvc-label">{t('checkpoints.revert.blocked')}</span>
        {#each preview.blocked_by as why (why)}<p>{why}</p>{/each}
      </div>
    {/if}
    {#if nothing}<p class="modal-description" data-revert-nothing="">{t('checkpoints.revert.nothing')}</p>{/if}
    <div class="rvc-lists" data-revert-lists="">
      {#each groups as [key, paths] (key)}
        {#if paths.length > 0}
          <section class="rvc-group" data-revert-group={key}>
            <span class="rvc-label">{t(`checkpoints.revert.${key}`, { n: paths.length })}</span>
            {#each paths as path (path)}<bdi class="rvc-path">{path}</bdi>{/each}
          </section>
        {/if}
      {/each}
      {#if preview.kept.length > 0}
        <section class="rvc-group" data-revert-group="kept">
          <span class="rvc-label">{t('checkpoints.revert.kept', { n: preview.kept.length })}</span>
          {#each preview.kept as k (k.path)}
            <bdi class="rvc-path">{k.path} <span class="rvc-why">{t(`checkpoints.revert.why.${k.reason}`)}</span></bdi>
          {/each}
        </section>
      {/if}
    </div>
  {/if}
  {#if failed}<p class="rvc-failed" role="alert" data-revert-failed="">{failed}</p>{/if}
  {#snippet footer()}
    <Button disabled={busy} onclick={() => close(null)}>{t('checkpoints.revert.cancel')}</Button>
    <Button variant="danger" data-revert-go="" disabled={busy || blocked} onclick={go}>{t('checkpoints.revert.go')}</Button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    .rvc-lists { display: flex; flex-direction: column; max-height: 40vh; overflow: auto; margin-top: var(--oc-space-2); }
    .rvc-group { display: flex; flex-direction: column; gap: var(--oc-space-0-5); padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-rule); }
    .rvc-label { font-family: var(--font-mono); font-size: var(--oc-fs-micro); letter-spacing: 0.12em; text-transform: uppercase; color: var(--oc-text-dim); }
    .rvc-path { font-family: var(--font-mono); font-size: var(--oc-fs-body); overflow-wrap: anywhere; }
    .rvc-why { color: var(--oc-text-dim); }
    .rvc-blocked, .rvc-failed { color: var(--oc-coral); }
    .rvc-blocked p { margin: var(--oc-space-0-5) 0 0; font-family: var(--font-mono); font-size: var(--oc-fs-body); }
  }
</style>

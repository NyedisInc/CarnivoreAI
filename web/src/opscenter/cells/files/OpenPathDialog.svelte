<script lang="ts">
  import { failureReason } from '../../../lib/errors/failure-reason';
  import ModalShell from '../../../lib/dialog-frame/ModalShell.svelte';
  import { Button, Field } from '../../../lib/base';
  import { openPathInFilesList } from '../../../lib/file-drawer/tree-api';
  import { t } from '../../../lib/i18n/index.svelte';
  import { fk } from './labels';
  import { PATH_MAX } from './state';

  let { open = $bindable(false), onOpened }: { open?: boolean; onOpened: () => void } = $props();

  let value = $state('');
  let error = $state('');
  let busy = $state(false);

  async function submit(): Promise<void> {
    if (busy) return;
    busy = true;
    error = '';
    try {
      await openPathInFilesList(value);
      open = false;
      onOpened();
    } catch (err) {
      error = failureReason(err);
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <ModalShell title={fk('path.title')} onCancel={() => { if (!busy) open = false; }} dismissable={!busy}>
    <form class="files-path-form" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
      <Field label={fk('path.label')} placeholder={fk('path.placeholder')} bind:value maxlength={PATH_MAX} {error} block />
      <div class="files-path-actions">
        <Button type="button" variant="quiet" onclick={() => (open = false)} disabled={busy}>{t('files.editor.cancel')}</Button>
        <Button type="submit" variant="confirm" disabled={busy || !value.trim()}>{fk('path.open')}</Button>
      </div>
    </form>
  </ModalShell>
{/if}

<style>
  @layer components {
    .files-path-form { display: grid; gap: var(--oc-space-3); }
    .files-path-actions { display: flex; justify-content: flex-end; gap: var(--oc-space-2); }
  }
</style>

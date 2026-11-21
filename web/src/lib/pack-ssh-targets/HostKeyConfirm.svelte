
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import ModalShell from '../dialog-frame/ModalShell.svelte';
  import type { HostKeyShown } from './ssh-targets-api';

  const { label, shown, close }: { label: string; shown: HostKeyShown; close: (value: string | null) => void } = $props();
  const first = $derived(shown.fingerprints[0] ?? { sha256: '', type: '' });
</script>

<ModalShell look="titlerow" width="min(34rem, 94vw)" title={t('pack.ssh.confirm.title', { name: label })} onCancel={() => close(null)}>
  <div data-ssh="confirm">
    <p class="modal-description">{t('pack.ssh.confirm.body')}</p>
    {#if shown.known === 'changed'}<p class="tm__problem" role="alert" data-ssh="confirm-changed">{t('pack.ssh.confirm.changed', { pinned: shown.pinned ?? '' })}</p>{/if}
    {#if shown.changed_since_shown}<p class="tm__problem" role="alert" data-ssh="confirm-moved">{t('pack.ssh.confirm.moved')}</p>{/if}
    <p class="tm__sub">{t('pack.ssh.confirm.shown', { type: first.type })}</p>
    <code class="pp-wrap" data-ssh="fingerprint">{first.sha256}</code>
  </div>
  {#snippet footer()}
    <Button variant="secondary" data-ssh="confirm-cancel" onclick={() => close(null)}>{t('pack.ssh.confirm.cancel')}</Button>
    <Button variant="confirm" data-ssh="confirm-go" onclick={() => close(first.sha256)}>{t('pack.ssh.confirm.go')}</Button>
  {/snippet}
</ModalShell>

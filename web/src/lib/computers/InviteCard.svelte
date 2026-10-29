<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import CopyField from '../settings-page/CopyField.svelte';
  import { activity, computers, dropInvite, reconcileInvite } from './computers-store.svelte';
  import { codeWords, countdown, passed } from './computers-format';

  let nowMs = $state(Date.now());
  const tick = setInterval(() => (nowMs = Date.now()), 1000);
  onDestroy(() => clearInterval(tick));

  const view = $derived(computers.data);
  const invite = $derived(activity.invite);
  const live = $derived(invite !== null && view !== null ? view.invites.find((i) => i.id === invite.id) : undefined);
  const paused = $derived(view?.self.link.code_paused_until ?? null);

  $effect(() => {
    const seen = view;
    untrack(() => reconcileInvite(seen));
  });
  $effect(() => {
    if (invite !== null && passed(invite.expires_at, nowMs)) activity.invite = null;
  });
</script>

{#if invite !== null}
  <div class="cmp-region cmp-invite" data-cmp="invite">
    <span class="pl-label">{t('computers.invite.code_label')}</span>
    {#if invite.code !== null && paused === null}
      <p class="cmp-code" data-cmp="code">{codeWords(invite.code)}</p>
    {:else}
      <p class="cmp-note" data-cmp="paused">{t('computers.invite.paused', { time: paused ?? '' })}</p>
    {/if}
    <p class="cmp-meta">
      <span data-cmp="countdown">{t('computers.invite.expires', { time: countdown(invite.expires_at, nowMs) })}</span>
      <span data-cmp="attempts">{t('computers.invite.attempts', { count: live?.attempts_left ?? invite.attempts_left })}</span>
      <span class="cmp-fp" data-cmp="self-fid">{t('computers.invite.self_fid', { fid: invite.fid_short })}</span>
    </p>
    <span class="pl-label">{t('computers.invite.link_label')}</span>
    <CopyField value={invite.link} {t} label={t('computers.invite.link_label')} valueAttrs={{ 'data-cmp': 'link' }} />
    <p class="cmp-note">{t('computers.invite.howto')}</p>
    <div class="cmp-actions">
      <button type="button" class="modal-btn modal-btn-secondary" data-cmp="invite-cancel" onclick={() => void dropInvite()}>
        {t('computers.invite.cancel')}
      </button>
    </div>
  </div>
{/if}

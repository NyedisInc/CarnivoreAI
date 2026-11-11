<script lang="ts">
  import './pack-machines.css';
  import './relay-consent.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import Button from '../base/Button.svelte';
  import { answerApproval } from './relay-approval-store.svelte';
  import { gateWord, globalSync, globalSyncActivity, saveGlobalSync, syncNow } from './global-sync-store.svelte';

  const view = $derived(globalSync.data);
  const s = $derived(view?.settings);
  const busy = $derived(globalSyncActivity.busy);

  function detail(c: { last: { sent?: { files?: number; refused_total?: number } } | null }): string {
    const sent = c.last?.sent;
    if (!sent || sent.files === undefined) return '';
    return t('pack.globalsync.sent', { files: sent.files, held: sent.refused_total ?? 0 });
  }
</script>

{#if view && view.is_main}
  <div class="pm-settings" data-pm="global-sync">
    <h3 class="pl-label">{t('pack.globalsync.title')}</h3>
    <p class="pm-note">{t('pack.globalsync.help')}</p>
    {#if globalSyncActivity.error}<p class="pm-error" role="alert" data-gs="error">{globalSyncActivity.error}</p>{/if}
    {#if s}
      <Check label={t('pack.globalsync.enabled')} checked={s.enabled} role="switch" disabled={busy} data-gs="enabled"
        onToggle={(next) => void saveGlobalSync({ enabled: next })} />
      {#if s.enabled}
        <Check label={t('pack.globalsync.auto')} hint={t('pack.globalsync.auto_help')} checked={s.auto} role="switch" disabled={busy} data-gs="auto"
          onToggle={(next) => void saveGlobalSync({ auto: next })} />
        <Check label={t('pack.globalsync.claude')} checked={s.claude} role="switch" disabled={busy} data-gs="claude"
          onToggle={(next) => void saveGlobalSync({ claude: next })} />
        <Check label={t('pack.globalsync.codex')} checked={s.codex} role="switch" disabled={busy} data-gs="codex"
          onToggle={(next) => void saveGlobalSync({ codex: next })} />
        {#each view.computers as c (c.install_id)}
          <div class="pm-relay-row" data-gs-computer={c.install_id}>
            <span>{c.label || c.install_id.slice(0, 8)}</span>
            <span class="pm-state" data-gs="state" data-gate={c.gate ?? ''}>{t(gateWord(c))}</span>
            {#if detail(c)}<span class="pm-state" data-gs="sent">{detail(c)}</span>{/if}
            {#if c.gate === 'not_approved'}
              <Button variant="confirm" data-gs="approve" disabled={busy} onclick={() => void answerApproval(c.install_id, 'yes')}>
                {t('pack.globalsync.approve')}</Button>
            {/if}
          </div>
        {/each}
        <div class="rc-actions">
          <Button variant="confirm" data-gs="sync-now" disabled={busy} onclick={() => void syncNow()}>{t('pack.globalsync.sync_now')}</Button>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<script lang="ts">
  import Button from '../base/Button.svelte';
  import Tag from '../base/Tag.svelte';
  import { t } from '../i18n/index.svelte';
  import { rowSwitchState } from './switch-model';
  import { accountSwitch, finishSetup, switchActivity, switchTo } from './switch-store.svelte';

  let {
    account,
    onLogin,
  }: {
    account: { id: string; name: string; provider: string; setup_complete?: boolean | null };
    onLogin?: () => void | Promise<void>;
  } = $props();

  let setupDone = $state(false);
  const rowState = $derived.by(() => {
    const state = rowSwitchState(accountSwitch.data, account);
    return state === 'needs_setup' && setupDone ? 'available' : state;
  });

  async function setUp(): Promise<void> {
    if ((await finishSetup(account.id, onLogin)) === 'done') setupDone = true;
  }

  const provider = $derived(
    account.provider === 'claude' || account.provider === 'codex'
      ? t(`ledger.editor.provider_${account.provider}`)
      : account.provider,
  );
  const busy = $derived(switchActivity.busy === account.id);
</script>

{#if rowState === 'active'}
  <Tag tone="info" data-asw>{t('account_switch.row.active')}</Tag>
{:else if rowState === 'needs_setup'}
  <Button
    data-asw
    data-tone="setup"
    title={t('account_switch.row.needs_setup_title', { name: account.name })}
    aria-label={t('account_switch.row.needs_setup_title', { name: account.name })}
    disabled={switchActivity.busy !== null}
    onclick={() => void setUp()}
    >{busy ? t('account_switch.row.setting_up') : t('account_switch.row.needs_setup')}</Button
  >
{:else if rowState === 'available'}
  <Button
    data-asw
    title={t('account_switch.row.switch_title', { provider, name: account.name })}
    aria-label={t('account_switch.row.switch_title', { provider, name: account.name })}
    disabled={switchActivity.busy !== null}
    onclick={() => void switchTo(account.id)}
    >{busy ? t('account_switch.row.switching') : t('account_switch.row.switch')}</Button
  >
{/if}

<style>
  @layer components {
    :global([data-asw]) {
      margin-left: auto;
      flex-shrink: 0;
    }

    :global([data-btn][data-asw]) {
      --_btn-h: 0px;
      --_btn-pad-y: var(--oc-border);
      --_btn-pad: var(--oc-space-1-5);
      --_btn-fs: var(--oc-fs-micro);
      --_btn-lh: 1.5;
    }

    :global([data-btn][data-asw][data-tone='setup']) {
      --_btn-ink: var(--oc-yellow);
    }

    :global([data-btn][data-asw][data-tone='setup']:hover:not(:disabled)) {
      text-decoration: underline;
      text-underline-offset: var(--oc-space-0-5);
    }
  }
</style>

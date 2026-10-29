<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Card from '../base/Card.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import Fold from '../base/Fold.svelte';
  import State from '../base/State.svelte';
  import Switch from '../base/Switch.svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import { restartSession } from '../launchpad/running-actions';
  import { browserRunningHost, type RunningHost } from '../launchpad/running-host';
  import type { RunningElsewhere } from './switch-model';
  import { resetAll, runningKey, type BulkPreview } from './reset-all';
  import {
    accountName,
    accountSwitch,
    loadRunningElsewhere,
    setAutoSwitch,
    switchActivity,
  } from './switch-store.svelte';

  const current = $derived(accountSwitch.data);
  const on = $derived(current?.auto_switch === true);
  const threshold = $derived(current?.threshold_percent ?? 99);
  let restarting = $state<string | null>(null);
  let resettingAll = $state(false);
  let confirmedKey = $state<string | null>(null);
  let bulkFailures = $state<string[]>([]);
  let bulkResult = $state<string | null>(null);
  let notice = $state<string | null>(null);
  const visibleKey = $derived(runningKey(switchActivity.running));
  const bulkConfirmed = $derived(confirmedKey !== null && confirmedKey === visibleKey);

  $effect(() => {
    if (confirmedKey !== null && confirmedKey !== visibleKey) confirmedKey = null;
  });

  let explained = $state(false);

  onMount(() => {
    void accountSwitch.refresh(true);
    void loadRunningElsewhere();
  });

  function providerName(provider: string): string {
    return provider === 'claude' || provider === 'codex' ? t(`ledger.editor.provider_${provider}`) : provider;
  }

  const lastLine = $derived.by((): string => {
    const last = current?.last_switch;
    if (!last) return '';
    const params = {
      provider: providerName(last.provider),
      from: accountName(last.from_account_id),
      to: accountName(last.to_account_id),
      percent: last.used_pct ?? '',
    };
    return t(`account_switch.last.${last.reason}`, params);
  });

  async function restartToSwitch(row: RunningElsewhere): Promise<void> {
    if (restarting || resettingAll) return;
    restarting = row.session_id;
    notice = null;
    const base = browserRunningHost();
    const host: RunningHost = {
      ...base,
      showError: (message: string) => {
        notice = message;
      },
      refresh: () => loadRunningElsewhere(),
      reopenAfterRestart: async () => ({ status: 'reopened', detail: null }),
    };
    try {
      await restartSession({ name: row.tmux_session, label: row.label, status: row.status }, host, t);
    } finally {
      restarting = null;
      await loadRunningElsewhere();
    }
  }

  async function restartAll(): Promise<void> {
    if (!bulkConfirmed || resettingAll || restarting || switchActivity.busy) return;
    const captured = switchActivity.running.map((row) => ({ ...row }));
    if (!captured.length || runningKey(captured) !== confirmedKey) return;
    resettingAll = true;
    switchActivity.busy = 'bulk';
    confirmedKey = null;
    bulkFailures = [];
    bulkResult = null;
    try {
      const result = await resetAll(captured, {
        running: () => authFetch<RunningElsewhere[]>('/provider-ledger/switch/running'),
        preview: (name): Promise<BulkPreview> => authFetch<BulkPreview>(
          `/sessions/restart/preview?session_name=${encodeURIComponent(name)}`,
        ),
        respawn: (name) => authFetch<{ ok?: boolean; detail?: string | null }>('/sessions/respawn', {
          method: 'POST',
          body: JSON.stringify({ session_name: name, confirm_restart_live: true }),
        }),
      });
      bulkFailures = result.failures.map(({ row, reason, detail }) => t(
        `account_switch.running.reset_${reason}`,
        { session: row.label || row.tmux_session, reason: detail || t('opscenter.value.read_failed') },
      ));
      bulkResult = t('account_switch.running.reset_result', {
        restarted: result.restarted,
        total: captured.length,
      });
    } finally {
      switchActivity.busy = null;
      resettingAll = false;
      await loadRunningElsewhere();
    }
  }
</script>


<Card data-ledger="auto-switch" title={t('account_switch.auto.title')} headingLevel={2}>
  {#snippet children()}
    
    <div class="asw-row">
      <p class="asw-hint">{t('account_switch.auto.hint', { percent: threshold })}</p>
      <Switch
        aria-label={t('account_switch.auto.title')}
        checked={on}
        data-on={on ? '1' : '0'}
        disabled={current === null || switchActivity.busy !== null}
        label={t(on ? 'account_switch.auto.on' : 'account_switch.auto.off')}
        onchange={(next) => void setAutoSwitch(next)}
      />
    </div>
    <Fold label={t('account_switch.auto.how')} bind:open={explained}>
      {#snippet children()}
        <p class="asw-explain">{t('account_switch.auto.explain', { percent: threshold })}</p>
        <p class="asw-explain">{t('account_switch.auto.running')}</p>
      {/snippet}
    </Fold>
    {#if lastLine}<p class="asw-last">{lastLine}</p>{/if}
    {#if switchActivity.error}<State kind="error" inline title={switchActivity.error} />{/if}
    {#if notice}<State kind="error" inline title={notice} />{/if}
    {#if bulkResult}<p class="asw-last" role="status">{bulkResult}</p>{/if}
    {#each bulkFailures as failure}<State kind="error" inline title={failure} />{/each}

    {#if switchActivity.running.length}
      <div class="asw-running-head">
        <h3 class="asw-running-title oc-label">{t('account_switch.running.title')}</h3>
        <div class="asw-bulk-actions">
          <Checkbox
            checked={bulkConfirmed}
            disabled={resettingAll || restarting !== null}
            label={t('account_switch.running.reset_confirm', { count: switchActivity.running.length })}
            onchange={(event) => { confirmedKey = event.currentTarget.checked ? visibleKey : null; }}
          />
          <Button
            variant="danger"
            disabled={!bulkConfirmed || resettingAll || restarting !== null || switchActivity.busy !== null}
            onclick={() => void restartAll()}
          >{t('account_switch.running.reset_all')}</Button>
        </div>
      </div>
      <ul class="asw-running">
        {#each switchActivity.running as row (row.session_id)}
          <li class="asw-running-row">
            <span class="asw-running-name">
              {t('account_switch.running.row', {
                session: row.label || row.tmux_session,
                account: accountName(row.account_id),
              })}
            </span>
            <Button
              data-asw-restart
              disabled={restarting !== null || resettingAll}
              onclick={() => void restartToSwitch(row)}
              >{t('account_switch.running.restart')}</Button
            >
          </li>
        {/each}
      </ul>
    {/if}
  {/snippet}
</Card>

<style>
  .asw-row {
    display: flex;
    align-items: center;
    gap: var(--oc-space-4);
  }

  .asw-hint {
    flex: 1 1 auto;
    min-width: 0;
    margin: 0;
    line-height: 1.45;
    color: var(--oc-text-secondary);
  }

  .asw-explain {
    margin: var(--oc-space-2) 0 0;
    max-width: 72ch;
    line-height: 1.5;
    color: var(--oc-text-secondary);
  }

  .asw-last {
    margin: 0;
    color: var(--oc-text-secondary);
  }

  .asw-running-title {
    margin: var(--oc-space-1) 0 0;
  }

  .asw-running-head, .asw-bulk-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--oc-space-3);
    flex-wrap: wrap;
  }

  .asw-running {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .asw-running-row {
    display: flex;
    align-items: center;
    gap: var(--oc-space-2);
    flex-wrap: wrap;
    padding: var(--oc-space-1-5) 0;
    box-shadow: inset 0 var(--oc-border) 0 0 var(--oc-line-hairline);
  }

  .asw-running-name {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .asw-running-row :global([data-asw-restart]) {
    margin-left: auto;
  }

  @media (max-width: 1023px) {
    .asw-row {
      align-items: flex-start;
    }

    @media (max-width: 767px) {
      .asw-row {
        flex-direction: column;
        gap: var(--oc-space-2);
      }
    }
  }
</style>

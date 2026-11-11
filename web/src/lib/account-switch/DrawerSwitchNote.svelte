<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import State from '../base/State.svelte';
  import { runningKey } from './reset-all';
  import { accountName, restartRunningBulk, switchActivity } from './switch-store.svelte';

  let { accountId }: { accountId: string } = $props();

  let confirmedKey = $state<string | null>(null);
  let restarting = $state(false);
  let failures = $state<string[]>([]);
  let result = $state<string | null>(null);
  const mine = $derived(switchActivity.target === accountId);
  const visibleKey = $derived(runningKey(switchActivity.running));
  const confirmed = $derived(confirmedKey !== null && confirmedKey === visibleKey);

  $effect(() => {
    if (!mine) {
      confirmedKey = null;
      failures = [];
      result = null;
    }
  });

  async function restartThem(): Promise<void> {
    const captured = switchActivity.running.map((row) => ({ ...row }));
    if (!confirmed || restarting || switchActivity.busy || !captured.length) return;
    restarting = true;
    confirmedKey = null;
    try {
      const done = await restartRunningBulk(captured);
      failures = done.failures;
      result = done.result;
    } finally {
      restarting = false;
    }
  }
</script>

{#if mine && (switchActivity.error || switchActivity.switched === accountId || result)}
  <div class="dsn" data-switch-note>
    {#if switchActivity.error}
      <State kind="error" inline title={switchActivity.error} />
    {:else if switchActivity.switched === accountId}
      <p class="dsn-line" role="status">{t('account_switch.note.switched', { name: accountName(accountId) })}</p>
    {/if}
    {#if switchActivity.switched === accountId && switchActivity.running.length}
      <p class="dsn-line" role="status">{t('account_switch.note.running', { count: switchActivity.running.length })}</p>
      <div class="dsn-actions">
        <Checkbox
          checked={confirmed}
          disabled={restarting}
          label={t('account_switch.note.confirm')}
          onchange={(event) => { confirmedKey = event.currentTarget.checked ? visibleKey : null; }}
        />
        <Button
          variant="danger"
          disabled={!confirmed || restarting || switchActivity.busy !== null}
          onclick={() => void restartThem()}>{t('account_switch.note.restart')}</Button
        >
      </div>
    {/if}
    {#if result}<p class="dsn-line" role="status">{result}</p>{/if}
    {#each failures as failure}<State kind="error" inline title={failure} />{/each}
  </div>
{/if}

<style>
  @layer components {
    .dsn {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      padding-top: var(--oc-space-1);
    }

    .dsn-line {
      margin: 0;
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
    }

    .dsn-actions {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      flex-wrap: wrap;
    }
  }
</style>

<script lang="ts">
  import { onDestroy } from 'svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { authFetch } from '../../opscenter/api/auth.svelte';
  import { resourcePush } from '../resource-push/boot';
  import { openSettingsLink } from '../settings-page/screen-host';
  import { t } from '../i18n/index.svelte';

  interface Status { feature_on: boolean; settings: { enabled: boolean }; login: { state: string; display_name: string } }
  interface Props { fetcher?: typeof authFetch; pollMs?: number }
  const { fetcher = authFetch, pollMs = 30000 }: Props = $props();

  let status = $state<Status | null>(null);
  const shown = $derived(!!status && status.feature_on && (status.login.state === 'logged_in' || status.login.state === 'login_soon'));
  const tethered = $derived(!!status?.settings?.enabled);
  const label = $derived(t(tethered ? 'argent.topbar.connected' : 'argent.topbar.connected_off', { name: status?.login.display_name ?? '' }));

  async function refresh(): Promise<void> {
    try {
      status = await fetcher<Status>('/argent/status');
    } catch {
      status = null;
    }
  }

  const stop = resourcePush().pushOrPoll(() => void refresh(), pollMs, ['argent_status']);
  void refresh();
  onDestroy(stop);
</script>

{#if shown}
  <button type="button" data-btn="quiet" data-size="icon" data-argent-topbar data-tether={tethered ? 'on' : 'off'} aria-label={label} data-tooltip={label}
    onclick={() => openSettingsLink('#settings/features/argent/settings')}>
    <Icon name="argent" size={16} />
  </button>
{/if}

<style>
  @layer components {
    [data-argent-topbar][data-tether='off'] { color: var(--oc-text-dim); }
  }
</style>

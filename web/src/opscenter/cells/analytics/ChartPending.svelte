
<script lang="ts">
  import State from '../../../lib/base/State.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { auth } from '../../api/auth.svelte';
  import { analytics, refreshAnalytics } from './state.svelte';

  const signedOut = $derived(auth.state === 'signed-out');
</script>

{#if signedOut}
  <State kind="empty" title={t('analytics.signed_out')} />
{:else if analytics.error}
  <State kind="error" title={t('analytics.chart_unavailable')} hint={analytics.error} onAction={() => void refreshAnalytics()} />
{:else if !analytics.loaded}
  <State kind="loading" title={t('analytics.loading')} />
{:else}
  <State kind="empty" title={t('analytics.chart_unavailable')} />
{/if}

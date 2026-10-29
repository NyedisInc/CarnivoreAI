<script lang="ts">
  import { Button, Field, Select } from '../../../lib/base';
  import { analytics, requestBackfill, setCollectionEnabled } from './state.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { live, watchLive } from '../../viz/noc-feed.svelte';

  $effect(() => watchLive());

  function setFilter(key: 'provider' | 'host' | 'project' | 'model' | 'agent_kind' | 'account_id' | 'window', value: string): void {
    analytics.filters[key] = value || undefined;
    analytics.revision++;
  }

  let notice = $state('');

  async function toggle(): Promise<void> {
    try { await setCollectionEnabled(!analytics.enabled); notice = ''; }
    catch (error) { notice = error instanceof Error ? error.message : t('analytics.setting_unavailable'); }
  }

  async function backfill(): Promise<void> {
    try { await requestBackfill(); notice = ''; }
    catch (error) { notice = error instanceof Error ? error.message : t('analytics.setting_unavailable'); }
  }
</script>

<div class="analytics-controls" role="group" aria-label="{t('analytics.history')}">
  <details class="analytics-options"><summary>{t('analytics.filters')}</summary><div class="analytics-options__body">
  <div class="analytics-options__fields">
  <label class="oc-select-row"><span class="oc-sub">{t('analytics.timezone')}</span> <Select size="sm" value={analytics.timezone} onchange={(event) => { analytics.timezone = event.currentTarget.value; analytics.revision++; }}>{#snippet children()}<option value={Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'}>{Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'}</option><option value="UTC">UTC</option>{/snippet}</Select></label>
  {#each ['provider', 'host', 'project', 'model', 'agent_kind', 'account_id', 'window'] as dimension (dimension)}
    <label class="oc-select-row"><span class="oc-sub">{t(`analytics.${dimension}`)}</span> <Select size="sm" value={analytics.filters[dimension as keyof typeof analytics.filters] || ''} onchange={(event) => setFilter(dimension as 'provider' | 'host' | 'project' | 'model' | 'agent_kind' | 'account_id' | 'window', event.currentTarget.value)}>{#snippet children()}
      <option value="">{t('analytics.all')}</option>
      {#each analytics.dimensions[dimension] || [] as item (item.key)}
        {#if item.filter_value}<option value={item.filter_value}>{item.label}</option>{/if}
      {/each}
    {/snippet}</Select></label>
  {/each}
  </div>
  <div class="analytics-options__actions">
  <Button size="sm" onclick={toggle} aria-pressed={analytics.enabled}>{analytics.enabled ? t('analytics.collection_on') : t('analytics.collection_off')}</Button>
  <Button size="sm" onclick={backfill} disabled={!analytics.enabled}>{t('analytics.backfill')}</Button>
  </div>
  {#if analytics.coverage}<p class="analytics-options__line" role="status">{analytics.coverage.minute_rows ?? 0} {t('analytics.minute_rows')} · {#if typeof analytics.coverage.freshness_seconds === 'number'}{analytics.coverage.freshness_seconds} {t('analytics.seconds_old')} · {/if}{analytics.coverage.quality_rows ?? 0} {t('analytics.quality_rows')} · {analytics.coverage.unknown_cost_rows ?? 0} {t('analytics.unknown_cost_rows')} · {Object.entries(analytics.coverage.backfill || {}).map(([state, count]) => `${state}: ${count}`).join(', ')}</p>{/if}
  {#if analytics.coverage}<details class="analytics-coverage"><summary>{t('analytics.coverage')}</summary><p>{t('analytics.db_size')}: {Math.round((analytics.coverage.db_bytes ?? 0) / 1024)} kb</p><p>{t('analytics.disabled_gaps')}: {analytics.coverage.disabled_spans?.length ?? 0}</p><p>{t('analytics.sources')}: {analytics.coverage.sources?.map((source) => `${source.status}/${source.quality}: ${source.count}`).join(', ') || t('analytics.none')}</p></details>{/if}
  {#if live.data}<p class="analytics-options__line" role="status">{t('analytics.live')} {live.data.state}{#if typeof live.data.metrics?.running_sessions === 'number'}: {live.data.metrics.running_sessions} {t('analytics.running')}{/if}{#if typeof live.data.metrics?.working_agents === 'number'} · {live.data.metrics.working_agents} {t('analytics.working')}{/if}</p>{/if}
  {#if notice}<p class="analytics-options__line analytics-options__notice" role="alert">{notice}</p>{/if}
  </div></details>
</div>

<style>
  @layer components {
    .analytics-controls { min-width: 0; color: var(--oc-text-secondary); font: var(--oc-fs-label) var(--font-mono); }

    .analytics-options summary { cursor: pointer; font-size: var(--oc-fs-micro); letter-spacing: 0.8px; text-transform: uppercase; }

    .analytics-options__body { display: flex; flex-direction: column; gap: var(--oc-space-3); padding-top: var(--oc-space-3); }

    .analytics-options__fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--oc-space-3); }

    .analytics-options__fields :global([data-field]) { width: 100%; min-width: 0; }

    .analytics-options__actions { display: flex; flex-wrap: wrap; gap: var(--oc-space-2); }

    .analytics-options__line { margin: 0; line-height: 1.5; overflow-wrap: anywhere; }

    .analytics-options__notice { color: var(--oc-coral); }

    .analytics-coverage summary { cursor: pointer; }

    .analytics-coverage p { margin: 2px 0; overflow-wrap: anywhere; }

    @media (max-width: 600px) { .analytics-options__fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  }
</style>

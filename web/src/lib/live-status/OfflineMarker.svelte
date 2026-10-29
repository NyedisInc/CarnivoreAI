<script lang="ts">
  import { onDestroy } from 'svelte';
  import { ageParts, connection, offlineAge, retryConnection } from './connection.svelte';
  import { t } from '../i18n/index.svelte';

  let now = $state(Date.now());
  let clock: ReturnType<typeof setInterval> | null = null;

  $effect(() => {
    if (connection.live) {
      if (clock !== null) clearInterval(clock);
      clock = null;
      return;
    }
    now = Date.now();
    if (clock === null) clock = setInterval(() => (now = Date.now()), 1000);
  });

  onDestroy(() => {
    if (clock !== null) clearInterval(clock);
  });

  const age = $derived(offlineAge(connection, now));
  const ago = $derived(age === null ? null : ageParts(age));
</script>

{#if ago}
  <div class="lsm" role="status" aria-live="polite" data-offline-marker>
    <span class="lsm-label">{t('live_status.offline')}</span>
    <span class="lsm-age">
      {t(connection.everLive ? 'live_status.last_live' : 'live_status.never_live', {
        age: t(`live_status.age.${ago.unit}`, { count: ago.count }),
      })}
    </span>
    <button type="button" class="lsm-retry" onclick={() => retryConnection()}>
      {t('live_status.retry')}
    </button>
  </div>
{/if}

<style>
  @layer components {
    .lsm {
      position: fixed;
      left: 8px;
      bottom: 8px;
      z-index: 9998;
      display: flex;
      align-items: center;
      gap: 8px;
      max-width: calc(100vw - 16px);
      padding: 3px 8px;
      border-radius: var(--oc-radius-sm);
      border: var(--oc-border) solid var(--oc-line-frame);
      background: var(--oc-ground-raised);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono, monospace);
      font-size: var(--oc-fs-micro);
      line-height: 1.4;
    }

    .lsm-label {
      color: var(--oc-orange);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      white-space: nowrap;
    }

    .lsm-age {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .lsm-retry {
      flex: none;
      padding: 0 6px;
      border-radius: var(--oc-radius-sm);
      border: var(--oc-border) solid var(--oc-line-frame);
      background: transparent;
      color: var(--oc-text-secondary);
      font: inherit;
      cursor: pointer;
    }

    .lsm-retry:hover {
      color: var(--oc-text-primary);
      background: var(--oc-ground-hover);
    }
  }
</style>

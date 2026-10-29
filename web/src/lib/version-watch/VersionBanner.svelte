<script lang="ts">
  import {
    bannerKind,
    dismissVersionBanner,
    loadWhatsNew,
    reloadForNewVersion,
    versionWatch,
    whatsNew,
  } from './version-watch.svelte';
  import { t } from '../i18n/index.svelte';

  const kind = $derived(bannerKind(versionWatch));
  const TYPE_ORDER = ['added', 'changed', 'fixed', 'security', 'deprecated', 'removed'];

  const rows = $derived(
    TYPE_ORDER.flatMap((type) =>
      whatsNew.entries
        .filter((e) => e.type === type)
        .map((e, i) => ({ ...e, first: i === 0 })),
    ),
  );

  let expanded = $state(false);
  let overflows = $state(false);
  let listEl: HTMLElement | undefined = $state();

  $effect(() => {
    if (kind) void loadWhatsNew();
  });

  $effect(() => {
    void rows;
    void expanded;
    if (listEl && !expanded) overflows = listEl.scrollHeight > listEl.clientHeight + 1;
  });
</script>

{#if kind}
  <div class="vb-banner" role="status" aria-live="polite">
    <div class="vb-head">
    <span class="vb-text">{t(kind === 'client' ? 'app_update.client_ready' : 'app_update.available')}</span>
    <button type="button" class="vb-reload" onclick={reloadForNewVersion}>
      {t('app_update.reload')}
    </button>
    <button
      type="button"
      class="vb-dismiss"
      aria-label={t('app_update.dismiss')}
      onclick={dismissVersionBanner}
    >
      &times;
    </button>
    </div>
    {#if rows.length > 0}
      <div class="vb-news">
        <span class="vb-label">{t('app_update.whats_new')}</span>
        <ul class="vb-list" class:vb-list--open={expanded} bind:this={listEl}>
          {#each rows as row}
            <li class="vb-row">
              <span class="vb-tag">{row.first ? t(`app_update.type.${row.type}`) : ''}</span>
              <span class="vb-item">
                {row.summary}
                {#if row.where.length > 0}
                  <span class="vb-where">{t('app_update.where', { where: row.where[0] })}</span>
                {/if}
              </span>
            </li>
          {/each}
          {#if expanded && whatsNew.more > 0}
            <li class="vb-row">
              <span class="vb-tag"></span>
              <span class="vb-where">{t('app_update.more', { count: whatsNew.more })}</span>
            </li>
          {/if}
        </ul>
        {#if overflows || expanded}
          <button type="button" class="vb-toggle" onclick={() => (expanded = !expanded)}>
            {t(expanded ? 'app_update.collapse' : 'app_update.expand')}
          </button>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .vb-banner {
    position: fixed;
    top: var(--desktop-inset-top, 0px);
    left: 50%;
    transform: translateX(-50%);
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: min(460px, calc(100vw - 32px));
    margin-top: 8px;
    padding: 6px 10px;
    border-radius: var(--oc-radius-sm, 4px);
    background: var(--oc-ground-raised, #061214);
    border: var(--oc-border, 1px) solid var(--oc-cyan, #2dd4bf);
    color: var(--oc-text-primary, #e6f1ee);
    font-size: var(--oc-fs-micro, 11px);
    line-height: 1.4;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  }

  .vb-head {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .vb-news {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding-top: 6px;
    border-top: var(--oc-border, 1px) solid var(--oc-line-rule);
    font-family: var(--font-mono, monospace);
  }

  .vb-label,
  .vb-tag {
    font-size: var(--oc-fs-micro, 10px);
    letter-spacing: var(--oc-tracking-label, 0.6px);
    text-transform: uppercase;
    color: var(--oc-text-secondary, #9fb3af);
  }

  .vb-label {
    color: var(--oc-orange, var(--oc-cyan, #2dd4bf));
  }

  .vb-list {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: calc(3 * 1.4em);
    overflow: hidden;
  }

  .vb-list--open {
    max-height: 50vh;
    overflow-y: auto;
  }

  .vb-row {
    display: grid;
    grid-template-columns: 6.5ch 1fr;
    column-gap: 8px;
  }

  .vb-item {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .vb-where {
    display: block;
    color: var(--oc-text-secondary, #9fb3af);
  }

  .vb-toggle {
    align-self: flex-start;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--oc-text-secondary, #9fb3af);
    font: inherit;
    cursor: pointer;
  }

  .vb-toggle:hover,
  .vb-toggle:focus-visible {
    color: var(--oc-text-primary, #e6f1ee);
  }

  .vb-text {
    white-space: nowrap;
  }

  .vb-reload {
    padding: 1px 8px;
    border-radius: var(--oc-radius-sm, 4px);
    border: var(--oc-border, 1px) solid var(--oc-cyan, #2dd4bf);
    background: transparent;
    color: var(--oc-cyan, #2dd4bf);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }

  .vb-reload:hover,
  .vb-reload:focus-visible {
    background: var(--oc-ground-hover, rgba(45, 212, 191, 0.12));
  }

  .vb-dismiss {
    padding: 0 4px;
    border: none;
    background: transparent;
    color: var(--oc-text-secondary, #9fb3af);
    font: inherit;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
  }

  .vb-dismiss:hover,
  .vb-dismiss:focus-visible {
    color: var(--oc-text-primary, #e6f1ee);
  }
</style>

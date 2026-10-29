<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { consequenceLines, detailLabel, headline, inUseLine } from './approval-display';
  import type { ApprovalDisplay } from './approvals-model';

  let { display = null, fallback = '', asker = '', id, extra }: {
    display?: ApprovalDisplay | null; fallback?: string; asker?: string; id: string; extra?: Snippet;
  } = $props();

  const lines = $derived(display ? consequenceLines(display) : []);
  const inUse = $derived(display ? inUseLine(display) : '');
  const rows = $derived(display?.detail ?? []);
</script>

<div class="ap-head" data-approval-head={id} data-tone={display?.tone ?? 'confirm'}>
  {#if display}
    <p class="ap-head__verb" data-approval-verb>{headline(display)}</p>
    {#if display.name}<p class="ap-head__name" data-approval-target>{display.name}</p>{/if}
    {#if inUse}
      <p class="ap-head__inuse" data-approval-in-use data-in-use-tone={display.in_use?.tone}>{inUse}</p>
    {/if}
    {#if lines.length}
      <ul class="ap-head__lines" data-approval-consequences>
        {#each lines as line, i (i)}<li class="ap-head__line">{line}</li>{/each}
      </ul>
    {/if}
  {:else if fallback}
    <p class="ap-head__line ap-head__line--solo" data-approval-fallback>{fallback}</p>
  {/if}
  {#if asker}<p class="ap-head__asker" data-approval-asker>{asker}</p>{/if}
  {#if rows.length || extra}
    <details class="ap-head__more" data-approval-detail>
      <summary class="ap-head__toggle">{t('approvals.display.details')}</summary>
      {#if rows.length}
        <dl class="ap-head__rows">
          {#each rows as row, i (i)}
            <dt class="ap-head__key">{detailLabel(row.key)}</dt>
            <dd class="ap-head__value">{row.value}</dd>
          {/each}
        </dl>
      {/if}
      {#if extra}{@render extra()}{/if}
    </details>
  {/if}
</div>

<style>
  @layer components {
    .ap-head {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
      font-family: var(--font-mono);
      --_tone: var(--oc-orange);
    }

    .ap-head[data-tone='danger'] {
      --_tone: var(--oc-coral);
    }

    .ap-head__verb {
      margin: 0;
      font-size: var(--oc-fs-label);
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--_tone);
    }

    .ap-head__name {
      margin: 0;
      font-size: var(--oc-fs-status);
      font-weight: 600;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
    }

    .ap-head__inuse {
      margin: 0;
      font-size: var(--oc-fs-label);
      font-weight: 600;
      color: var(--oc-text-secondary);
      overflow-wrap: anywhere;
    }

    .ap-head__inuse[data-in-use-tone='alert'] {
      color: var(--oc-coral);
    }

    .ap-head__lines {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .ap-head__line {
      margin: 0;
      padding-left: var(--oc-space-3);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
      box-shadow: inset var(--oc-border, 1px) 0 0 0 var(--oc-line-panel);
    }

    .ap-head__line--solo {
      padding-left: 0;
      box-shadow: none;
    }

    .ap-head__asker {
      margin: 0;
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
      overflow-wrap: anywhere;
    }

    .ap-head__toggle {
      cursor: pointer;
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-secondary);
    }

    .ap-head__toggle:hover {
      color: var(--oc-text-primary);
    }

    .ap-head__rows {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: var(--oc-space-1) var(--oc-space-2);
      margin: var(--oc-space-1) 0 0;
      font-size: var(--oc-fs-micro);
    }

    .ap-head__key {
      color: var(--oc-text-secondary);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .ap-head__value {
      margin: 0;
      color: var(--oc-text-primary);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .ap-head__more {
      min-width: 0;
    }
  }
</style>

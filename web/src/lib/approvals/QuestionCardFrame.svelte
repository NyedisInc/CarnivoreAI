<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { reviewLines } from '../code-review/risk';
  import { detailLabel } from './approval-display';
  import { factText, say, type CardContract } from './card-contract';

  let { id, contract, open = $bindable(true), foldable = false, age = '', onToggle, children, foot }: {
    id: string; contract: CardContract; open?: boolean; foldable?: boolean; age?: string;
    onToggle?: (open: boolean) => void; children?: Snippet; foot?: Snippet;
  } = $props();

  const lines = $derived(contract.raw?.kind === 'code' ? reviewLines(contract.raw.code) : []);
  const shown = $derived(open || !foldable);

  function toggle(): void {
    open = !open;
    onToggle?.(open);
  }
</script>

{#snippet head()}
  <span class="qc-head">
    <span class="qc-badge" data-qc-badge>{t(`approvals.card.badge.${contract.kind}`)}</span>
    {#if contract.who}<span class="qc-who" data-qc-who>{contract.who}</span>{/if}
    <span class="qc-where">{contract.where}</span>
    {#if contract.host}<span class="qc-host" data-approval-host>{contract.host}</span>{/if}
    {#if age}<span class="qc-age" data-qc-age>{age}</span>{/if}
    {#if foldable}<span class="qc-chev" aria-hidden="true">{open ? '-' : '+'}</span>{/if}
  </span>
  <span class="qc-hl" data-qc-headline>{say(contract.headline)}</span>
{/snippet}

<div class="qc-card" data-qc-card={id} data-tone={contract.tone} data-qc-folded={shown ? undefined : ''}>
  {#if foldable}
    <button type="button" class="qc-toggle" data-qc-toggle aria-expanded={open} onclick={toggle}>{@render head()}</button>
  {:else}
    <div class="qc-toggle qc-toggle--still">{@render head()}</div>
  {/if}
  {#if shown}
    {#if contract.facts.length}
      <dl class="qc-facts" data-qc-facts>
        {#each contract.facts as fact, i (i)}
          <dt class="qc-fact__key">{t(`approvals.card.fact.${fact.id}`)}</dt>
          <dd class="qc-fact__value" class:qc-fact__value--wrap={fact.wrap} class:qc-fact__value--warn={fact.tone === 'warn'}
            data-qc-fact={fact.id} title={fact.full}>{factText(fact)}</dd>
        {/each}
      </dl>
    {/if}
    {@render children?.()}
    {#if contract.raw}
      <div class="qc-more-row">
        {#if contract.raw}
          <details class="qc-more" data-qc-details open={contract.raw.kind === 'code'}>
            <summary class="qc-more__toggle">{t('approvals.display.details')}</summary>
            {#if contract.raw.kind === 'code'}
              <div class="qc-raw" role="group" data-approval-body data-approval-code aria-label={t('approvals.body_label')}>{#each lines as line (line.n)}<code class="ap-line" class:ap-line--risk={line.risks.length > 0} data-risk={line.risks.length > 0 ? line.risks.join(' ') : undefined}>{line.text}</code>{/each}</div>
            {:else if contract.raw.kind === 'agent'}
              {#if contract.raw.rows.length}
                <dl class="qc-raw__rows" data-approval-detail>
                  {#each contract.raw.rows as row, i (i)}
                    <dt class="qc-fact__key">{detailLabel(row.key)}</dt>
                    <dd class="qc-raw__value">{row.value}</dd>
                  {/each}
                </dl>
              {/if}
              {#if contract.raw.text}<pre class="qc-raw" data-approval-body aria-label={t('approvals.body_label')}>{contract.raw.text}</pre>{/if}
            {:else}
              <pre class="qc-raw" data-approval-body aria-label={t('approvals.body_label')}>{contract.raw.text}</pre>
            {/if}
          </details>
        {/if}
      </div>
    {/if}
    {@render foot?.()}
  {/if}
</div>

<style>
  @layer components {
    .qc-card {
      --_k: var(--oc-yellow);
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      min-width: 0;
      padding: var(--oc-space-2) 10px;
      box-shadow: inset 3px 0 0 0 var(--_k);
      font-family: var(--font-mono);
      color: var(--oc-text-primary);
    }
    .qc-card[data-tone='perm'] { --_k: var(--oc-cyan); }
    .qc-card[data-tone='ask'] { --_k: var(--oc-violet); }
    .qc-card[data-tone='plan'] { --_k: var(--oc-green); }
    .qc-card[data-tone='agent'] { --_k: var(--oc-orange); }
    .qc-card[data-tone='codex'] { --_k: var(--oc-text-secondary); }
    .qc-card[data-tone='raw'] { --_k: var(--oc-text-dim); }
    .qc-card[data-qc-folded] { gap: 0; }

    .qc-toggle {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      width: 100%;
      min-width: 0;
      margin: 0;
      padding: 0;
      background: transparent;
      border: 0;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .qc-toggle--still { cursor: default; }
    .qc-head { display: flex; align-items: center; gap: var(--oc-space-1-5); min-width: 0; font-size: var(--oc-fs-label); }

    .qc-badge {
      flex: none;
      padding: 0 5px;
      border: var(--oc-border, 1px) solid var(--_k);
      border-radius: var(--oc-radius-sm, 2px);
      color: var(--_k);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 16px;
      text-transform: uppercase;
    }
    .qc-who { min-width: 0; overflow: hidden; color: var(--oc-text-bright); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
    .qc-where { flex: 1; min-width: 0; overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }
    .qc-host {
      flex: 0 1 auto;
      min-width: 0;
      max-width: 45%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      padding: 0 var(--oc-space-1);
      border: var(--oc-border, 1px) solid var(--oc-cyan);
      border-radius: var(--oc-radius-sm, 2px);
      color: var(--oc-cyan);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .qc-age { flex: none; color: var(--oc-text-dim); font-size: var(--oc-fs-micro); letter-spacing: 0.06em; text-transform: uppercase; font-variant-numeric: tabular-nums; }
    .qc-chev { flex: none; width: 1ch; color: var(--oc-text-dim); }
    .qc-toggle:hover .qc-chev { color: var(--oc-text-primary); }

    .qc-hl { font-size: var(--oc-fs-body); line-height: 1.4; color: var(--oc-text-bright); overflow-wrap: anywhere; }

    .qc-facts { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 1px 10px; margin: 0; font-size: var(--oc-fs-label); }
    .qc-fact__key { color: var(--oc-text-dim); font-size: var(--oc-fs-micro); letter-spacing: 0.08em; line-height: 18px; text-transform: uppercase; }
    .qc-fact__value { min-width: 0; margin: 0; overflow: hidden; color: var(--oc-text-secondary); line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
    .qc-fact__value--wrap { white-space: normal; overflow-wrap: anywhere; }
    .qc-fact__value--warn { color: var(--oc-coral); }

    .qc-more-row { display: flex; align-items: flex-start; gap: var(--oc-space-2); min-width: 0; }
    .qc-more { flex: 1; min-width: 0; }
    .qc-more__toggle {
      width: max-content;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      text-decoration: underline;
      text-underline-offset: 2px;
      cursor: pointer;
    }
    .qc-more__toggle:hover { color: var(--oc-text-primary); }
    .qc-raw {
      margin: var(--oc-space-1) 0 0;
      padding: var(--oc-space-1-5) var(--oc-space-2);
      max-height: 13em;
      overflow: auto;
      background: var(--oc-ground-field);
      border-radius: var(--oc-radius-sm, 2px);
      box-shadow: inset 0 0 0 var(--oc-border, 1px) var(--oc-line-panel);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    /* the code review modal */
    .qc-raw .ap-line { display: block; font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; min-height: 1.2em; box-shadow: inset 2px 0 0 0 transparent; padding-left: var(--oc-space-1); }
    .qc-raw .ap-line--risk { background: color-mix(in oklab, var(--oc-coral) 14%, transparent); box-shadow: inset 2px 0 0 0 var(--oc-coral); }
    .qc-raw__rows { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 1px 10px; margin: var(--oc-space-1) 0 0; font-size: var(--oc-fs-label); }
    .qc-raw__value { margin: 0; color: var(--oc-text-secondary); overflow-wrap: anywhere; }

    @container oc-ap (max-width: 260px) {
      .qc-raw { max-height: 6em; }
    }
  }
</style>

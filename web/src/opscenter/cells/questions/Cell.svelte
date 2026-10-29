<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const QUESTIONS_WIDGET = defineWidget({ id: 'core.questions', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import '../../../lib/ledger/ledger-chrome.css';
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import Icon from '../../ui/Icon.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import type { QuestionRow } from './model';
  import { attentionBroken, attentionUnread, startAttentionSources } from '../../../lib/attention-kinds/read.svelte';
  import { openAttention } from '../../../lib/attention-kinds/open';
  import { questionCount, questionRows } from './state.svelte';
  import { ageText } from './age';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import State from '../../../lib/base/State.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  const AGE_STEP_MS = 30_000;

  let props: CellProps = $props();
  const limit = $derived(props.limit ?? null);
  const options = $derived(props.options);
  const widget = useWidget(QUESTIONS_WIDGET, () => props);

  let now = $state(Date.now());
  let failed = $state('');

  $effect(() => startClock());
  $effect(() => {
    void clock.now;
    const at = Date.now();
    if (at - untrack(() => now) >= AGE_STEP_MS) now = at;
  });

  const rows = $derived(questionRows(options));
  const shown = $derived(limit === null ? rows : rows.slice(0, limit));
  const total = $derived(questionCount(options));
  const unread = $derived(attentionUnread());
  const broken = $derived(rows.length === 0 && attentionBroken());

  const MARKS = { approval: 'check-circle', huddle: 'chat', alert: 'bell', automation: 'clock' } as const;

  async function open(row: QuestionRow): Promise<void> {
    const outcome = await openAttention(row.target);
    failed = outcome.failedKey ? t(outcome.failedKey) : outcome.failedText;
  }
</script>

<WidgetShell {widget}>
<div class="pledger oc-qs-cell" data-questions-cell>
  {#if rows.length === 0}
    <State inline kind={broken ? 'error' : 'empty'} data-questions-empty title={broken ? t('opscenter.cell.questions.load_failed') : unread ? '' : t('opscenter.cell.questions.empty')} />
  {/if}
  {#if total}<p class="oc-qs-count" data-questions-count={total}>{t('opscenter.cell.questions.count', { count: total })}</p>{/if}
  <ul class="oc-qs-list" aria-label={t('opscenter.cell.questions.list')}>
    {#each shown as row (row.key)}
      <li>
        <button type="button" class="oc-qs-row" data-question-row={row.key} data-question-source={row.source} onclick={() => void open(row)}>
          <span class="oc-qs-mark"><Icon name={MARKS[row.source]} size={12} /></span>
          <span class="oc-qs-body">
            <span class="oc-qs-what">{row.what}</span>
            <span class="oc-qs-meta">
              <span class="oc-qs-kind">{row.source === 'alert' ? row.sender : t(`opscenter.cell.questions.kind.${row.source}`)}</span>
              {#if row.where}<span class="oc-qs-where">{row.where}</span>{/if}
              {#if row.atMs !== null}<span class="oc-qs-age">{ageText(row.atMs, now)}</span>{/if}
            </span>
          </span>
        </button>
      </li>
    {/each}
  </ul>
  {#if failed}<State kind="error" inline data-questions-failed title={failed} />{/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-qs-cell {
      height: 100%;
      overflow-y: auto;
      min-height: 0;
      font-family: var(--font-mono);
      container: oc-qs / inline-size;
    }

    .oc-qs-count {
      margin: 0;
      padding: var(--oc-space-1) var(--oc-space-3);
      font-size: var(--oc-fs-label);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--oc-yellow);
      font-variant-numeric: tabular-nums;
      box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .oc-qs-list { list-style: none; margin: 0; padding: 0; }

    .oc-qs-list > li + li { box-shadow: inset 0 1px 0 0 var(--oc-line-faint); }

    .oc-qs-row {
      display: flex;
      align-items: flex-start;
      gap: var(--oc-space-2);
      width: 100%;
      min-width: 0;
      padding: var(--oc-space-2) var(--oc-space-3);
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-primary);
      font: inherit;
      font-size: var(--oc-fs-body);
      text-align: left;
      cursor: pointer;
    }

    .oc-qs-row:hover { background: var(--oc-ground-hover); }

    .oc-qs-mark { flex: 0 0 auto; padding-top: var(--oc-space-1); color: var(--oc-yellow); }

    .oc-qs-row[data-question-source='huddle'] .oc-qs-mark { color: var(--oc-cyan); }

    .oc-qs-row[data-question-source='automation'] .oc-qs-mark { color: var(--oc-coral); }

    .oc-qs-row[data-question-source='alert'] .oc-qs-mark { color: var(--oc-text-secondary); }

    .oc-qs-body { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: var(--oc-space-1); }

    .oc-qs-what {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      overflow-wrap: anywhere;
    }

    .oc-qs-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0 var(--oc-space-2);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
    }

    .oc-qs-kind { text-transform: uppercase; letter-spacing: 0.08em; }

    .oc-qs-where { min-width: 0; overflow-wrap: anywhere; }

    .oc-qs-age { color: var(--oc-text-muted); }
  }
</style>

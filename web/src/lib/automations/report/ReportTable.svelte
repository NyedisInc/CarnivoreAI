
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import { getContext } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { isScalar } from '../logic/diff';
  import { unionKeys } from '../logic/report-rules';
  import { humanKey } from '../logic/words';
  import ReportTree, { REPORT_CTX, type ReportCtx } from './ReportTree.svelte';

  type Obj = Record<string, unknown>;
  let { rows, firstCol = null }: { rows: Obj[]; firstCol?: string | null } = $props();
  const ctx = getContext<ReportCtx | undefined>(REPORT_CTX);
  const CAP = 50;

  const keys = $derived(unionKeys(rows).filter((k) => k !== 'fix_prompt' && k !== '__k'));
  const shown = $derived(keys.slice(0, 8));
  const rest = $derived(keys.slice(8));
  const numeric = $derived(shown.map((k) => rows.every((r) => typeof r[k] === 'number' || r[k] === null || r[k] === undefined) && rows.some((r) => typeof r[k] === 'number')));
  const fixable = (r: Obj): boolean => typeof r.fix_prompt === 'string' && typeof r.finding_id === 'string' && !!r.finding_id;
  const hasFix = $derived(!!ctx?.fix && rows.some(fixable));

  let sortCol = $state<number | null>(null);
  let dir = $state<'asc' | 'desc'>('asc');
  let all = $state(false);

  function sortValue(r: Obj, col: number): number | string {
    const k = firstCol ? (col === 0 ? '__k' : shown[col - 1]!) : shown[col]!;
    const v = r[k];
    if (typeof v === 'number') return v;
    return v === null || v === undefined || !isScalar(v) ? '' : String(v).toLowerCase();
  }
  const ordered = $derived.by(() => {
    if (sortCol === null) return rows;
    const col = sortCol;
    const sign = dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = sortValue(a, col);
      const y = sortValue(b, col);
      return sign * (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y)));
    });
  });
  const visible = $derived(all ? ordered : ordered.slice(0, CAP));

  function sortBy(col: number): void {
    dir = sortCol === col && dir === 'asc' ? 'desc' : 'asc';
    sortCol = col;
  }
  function onKey(e: KeyboardEvent, col: number): void {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      sortBy(col);
    }
  }
  const ariaSort = (col: number): 'ascending' | 'descending' | undefined => (sortCol === col ? (dir === 'asc' ? 'ascending' : 'descending') : undefined);
  const base = $derived(firstCol ? 1 : 0);
</script>

{#snippet cell(v: unknown, k: string)}
  {#if isScalar(v)}
    {#if typeof v === 'string' && v.length > 300}
      <ReportTree value={v.slice(0, 300)} keyName={k} /><span class="r-note"> {t('automations.page.report.more_chars', { n: v.length - 300 })}</span>
    {:else}
      <ReportTree value={v} keyName={k} />
    {/if}
  {:else if !(Array.isArray(v) ? v.length : Object.keys(v as Obj).length)}
    <span class="r-null">{Array.isArray(v) ? t('automations.page.report.none') : t('automations.page.report.empty')}</span>
  {:else}
    <details class="r-more r-cell">
      <summary>{Array.isArray(v) ? t('automations.page.diff.items', { n: v.length }) : t('automations.page.diff.fields', { n: Object.keys(v as Obj).length })}</summary>
      <ReportTree value={v} keyName={k} depth={2} />
    </details>
  {/if}
{/snippet}

<div class="r-scroll">
  <table class="r-table">
    <thead>
      <tr>
        {#if firstCol}
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
          <th tabindex="0" data-sort="0" aria-sort={ariaSort(0)} onclick={() => sortBy(0)} onkeydown={(e) => onKey(e, 0)}>{firstCol}</th>
        {/if}
        {#each shown as k, c (k)}
          <!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
          <th tabindex="0" data-sort={c + base} aria-sort={ariaSort(c + base)} onclick={() => sortBy(c + base)} onkeydown={(e) => onKey(e, c + base)}>{humanKey(k)}</th>
        {/each}
        {#if rest.length}<th>{t('automations.page.report.more_cols_head')}</th>{/if}
        {#if hasFix}<th></th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each visible as r, i (i)}
        <tr>
          {#if firstCol}<th scope="row">{r.__k}</th>{/if}
          {#each shown as k, c (k)}
            <td class={numeric[c] ? 'ap-num r-num' : undefined}>{@render cell(r[k], k)}</td>
          {/each}
          {#if rest.length}
            <td>
              <details class="r-more">
                <summary>{t('automations.page.report.more_cols', { n: rest.length })}</summary>
                <dl class="r-kv">
                  {#each rest as k (k)}<div><dt>{humanKey(k)}</dt><dd>{@render cell(r[k], k)}</dd></div>{/each}
                </dl>
              </details>
            </td>
          {/if}
          {#if hasFix}
            <td>
              {#if fixable(r)}
                <Button size="sm" data-fix={String(r.finding_id)} onclick={() => ctx?.fix?.(String(r.finding_id))}>{t('automations.page.report.fix_it')}</Button>
              {/if}
            </td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
{#if !all && ordered.length > CAP}
  <div class="r-clipbar"><Button size="sm" data-r-rows onclick={() => (all = true)}>{t('automations.page.report.show_all_rows', { n: ordered.length })}</Button></div>
{/if}

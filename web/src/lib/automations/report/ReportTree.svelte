
<script module lang="ts">
  import { RUN_MARKS, type MarkName } from '../logic/marks';

  export const REPORT_CTX = 'automations-report';

  export interface ReportCtx {
    truncated: boolean;
    fix: ((findingId: string) => void) | null;
  }

  export { mark };
</script>

{#snippet mark(name: MarkName, size: number, label: string)}
  <svg class="mk-run" data-status={name} width={size} height={size} viewBox="0 0 14 14" role="img" aria-label={label}>
    {#each RUN_MARKS[name] as part, i (i)}<svelte:element this={part.tag} {...part.attrs} />{/each}
  </svg>
{/snippet}

<script lang="ts">
  import Fold from '../../base/Fold.svelte';
  import Tag from '../../base/Tag.svelte';
  import { getContext } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { isObj, isScalar } from '../logic/diff';
  import { wordKind, wordMark } from '../logic/marks';
  import { likeKeys, sameKeys } from '../logic/report-rules';
  import { fmtNum, humanKey } from '../logic/words';
  import LongText from './LongText.svelte';
  import ReportTable from './ReportTable.svelte';
  import RowsFold from './RowsFold.svelte';
  import ReportTree from './ReportTree.svelte';

  let { value, keyName = '', depth = 0 }: { value: unknown; keyName?: string; depth?: number } = $props();
  const ctx = getContext<ReportCtx | undefined>(REPORT_CTX);
  type Obj = Record<string, unknown>;

  const count = (v: unknown): number => (Array.isArray(v) ? v.length : Object.keys(v as Obj).length);
  const isFlat = (o: Obj): boolean => Object.values(o).every(isScalar);
  const asTable = (o: Obj): Obj[] | null => {
    const keys = Object.keys(o);
    const vals = keys.map((k) => o[k]);
    if (keys.length >= 2 && vals.every(isObj) && sameKeys(vals) && Object.keys(vals[0] as Obj).length) return keys.map((k) => ({ __k: k, ...(o[k] as Obj) }));
    return null;
  };
</script>

{#snippet scalar(v: unknown, key: string)}
  {#if v === null || v === undefined}
    <span class="r-null">{t('automations.page.report.none')}</span>
  {:else if typeof v === 'boolean'}
    <span class="r-s">{String(v)}</span>
  {:else if typeof v === 'number'}
    <span class="r-n ap-num">{fmtNum(v, key)}</span>
  {:else if wordKind(v)}
    <span class="r-w">{@render mark(wordMark(v)!, 10, String(v).trim().toLowerCase())} <span>{v}</span></span>
  {:else if String(v).includes('\n') || String(v).length > 160}
    <LongText text={String(v)} truncated={ctx?.truncated ?? false} />
  {:else}
    <span class="r-s">{v}</span>
  {/if}
{/snippet}

{#if isScalar(value)}
  {@render scalar(value, keyName)}
{:else if Array.isArray(value)}
  {#if !value.length}
    <span class="r-null">{t('automations.page.report.none')}</span>
  {:else if value.every(isScalar)}
    <ul class="r-chips">
      {#each value.slice(0, 20) as v, i (i)}<li><Tag>{@render scalar(v, '')}</Tag></li>{/each}
      {#if value.length > 20}<li class="r-more">{t('automations.page.report.more_chips', { n: value.length - 20 })}</li>{/if}
    </ul>
  {:else if likeKeys(value)}
    <RowsFold rows={value} />
  {:else}
    <div class="r-tree">
      {#each value.slice(0, 50) as x, i (i)}
        {@render branch(t('automations.page.report.item_n', { n: i + 1 }), x, depth + 1, '')}
      {/each}
      {#if value.length > 50}<div class="r-note">{t('automations.page.report.more_items', { n: value.length - 50 })}</div>{/if}
    </div>
  {/if}
{:else if !Object.keys(value as Obj).length}
  <span class="r-null">{t('automations.page.report.empty')}</span>
{:else if isFlat(value as Obj)}
  <dl class="r-kv">
    {#each Object.entries(value as Obj) as [k, v] (k)}
      <div><dt>{humanKey(k)}</dt><dd>{@render scalar(v, k)}</dd></div>
    {/each}
  </dl>
{:else if asTable(value as Obj)}
  <ReportTable rows={asTable(value as Obj)!} firstCol={t('automations.page.report.table_name')} />
{:else}
  <div class="r-tree">
    {#each Object.entries(value as Obj) as [k, v] (k)}
      {@render branch(humanKey(k), v, depth, k)}
    {/each}
  </div>
{/if}

{#snippet branch(label: string, v: unknown, d: number, rawKey: string)}
  {#if isScalar(v)}
    <div class="r-row"><span class="r-k">{label}</span><span class="r-v">{@render scalar(v, rawKey || label)}</span></div>
  {:else}
    <div class="r-branch">
      <Fold {label} count={count(v)} open={d < 2}>
        {#snippet children()}
          <div class="r-branch-body"><ReportTree value={v} keyName={rawKey || label} depth={d + 1} /></div>
        {/snippet}
      </Fold>
    </div>
  {/if}
{/snippet}

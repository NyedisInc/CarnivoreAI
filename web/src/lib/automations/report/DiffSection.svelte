
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import Tag from '../../base/Tag.svelte';
  import { tagClass } from '../../base/classes';
  import { t } from '../../i18n/index.svelte';
  import { countWords, fmtNum } from '../logic/words';
  import type { DiffEntry, DiffResult } from '../logic/diff';

  interface Props {
    result: DiffResult;
    heading?: string | null;
    showAll?: boolean;
    onToggleAll?: () => void;
  }
  let { result, heading = null, showAll = false, onToggleAll }: Props = $props();
  const g = $derived(result.groups);
  const groups = $derived<[string, DiffEntry[]][]>([
    [t('automations.page.diff.group.new'), g.appeared],
    [t('automations.page.diff.group.cleared'), g.cleared],
    [t('automations.page.diff.group.numbers'), g.numbers.slice(0, 10)],
    [t('automations.page.diff.group.values'), g.strings],
    [t('automations.page.diff.group.text'), g.texts],
  ]);
  const gutter = (e: DiffEntry): string => (e.kind === 'appeared' ? '+' : e.kind === 'cleared' ? '-' : '~');
  const isScalar = (v: unknown): boolean => v === null || typeof v !== 'object';
  const none = (v: unknown): string => (v === null || v === undefined ? t('automations.page.report.none') : String(v));
  const sign = (n: number): string => (n > 0 ? '+' : '-');
</script>

{#snippet body()}
  <div class="r-chg" data-same={result.same}>
    <p class="r-chg-s" data-sentence>
      {result.sentence}{#if result.base && !result.same}{' '}<span class="r-sub">{t('automations.page.diff.against', { n: result.base.number })}</span>{/if}
    </p>
    {#if result.deltas.length}
      <div class="r-chips-line">
        {#each result.deltas as d (d.label)}<Tag><i>{d.label}</i> {d.text}</Tag>{/each}
      </div>
    {/if}
    {#each groups as [name, list] (name)}
      {#if list.length}
        <section class="r-sec">
          <h3 class="r-h">{name} <span class="{tagClass('neutral')} r-badge">{list.length}</span></h3>
          <ul class="r-cl">
            {#each list as e, i (i)}
              <li data-kind={e.kind}>
                <span class="r-gut">{gutter(e)}</span><span class="r-cl-label">{e.label}</span>
                {#if e.kind === 'appeared' || e.kind === 'cleared'}
                  <span class="r-cl-val">{#if isScalar(e.value) && String(e.value) !== e.label}{none(e.value)}{/if}</span>
                {:else if e.kind === 'number'}
                  <span class="r-cl-val ap-num">{fmtNum(Number(e.old), e.path)} → {fmtNum(Number(e.new), e.path)} ({sign(e.delta ?? 0)}{fmtNum(Math.abs(e.delta ?? 0), e.path)}{#if e.pct != null}, {e.pct > 0 ? '+' : ''}{Math.round(e.pct)}%{/if})</span>
                {:else if e.kind === 'string'}
                  <span class="r-cl-val"><s>{none(e.old)}</s> {none(e.new)}</span>
                {:else if e.lines}
                  <span class="r-cl-val">{t('automations.page.diff.lines', { added: t(e.lines.added.length === 1 ? 'automations.page.diff.line_added_one' : 'automations.page.diff.lines_added', { n: e.lines.added.length }), removed: e.lines.removed.length })}</span>
                  <pre class="r-lines">{#each e.lines.ops.slice(0, 5) as o, j (j)}{#if j > 0}{'\n'}{/if}<span data-t={o.t === '+' ? 'add' : 'del'}>{o.t} {o.line}</span>{/each}{#if e.lines.ops.length > 5}{'\n'}<span>{t('automations.page.diff.more_lines', { n: e.lines.ops.length - 5 })}</span>{/if}</pre>
                {/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/each}
    {#if g.numbersMore}<div class="r-note">{t('automations.page.diff.more_numbers', { n: g.numbersMore })}</div>{/if}
    {#if result.ignored || showAll}
      <div class="r-note">
        {showAll ? t('automations.page.diff.showing_volatile') : t('automations.page.diff.volatile', { n: countWords('automations.page.count.volatile', result.ignored) })}
        <Button size="sm" data-diff-all={showAll ? '0' : '1'} onclick={() => onToggleAll?.()}>{showAll ? t('automations.page.diff.hide_volatile') : t('automations.page.diff.show_all')}</Button>
      </div>
    {/if}
  </div>
{/snippet}

{#if heading !== null}
  <Card title={heading} data-part="changes">
    {@render body()}
  </Card>
{:else}
  <div data-part="changes">{@render body()}</div>
{/if}

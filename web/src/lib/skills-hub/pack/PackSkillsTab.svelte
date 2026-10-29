
<script lang="ts">
  import ManagerFrame from '../../manager-frame/ManagerFrame.svelte';
  import { viewport } from '../../../opscenter/engine/viewport.svelte';
  import { t as appT } from '../../i18n/index.svelte';
  import type { Translate } from '../../sessions/types';
  import '../local/local-skills.css';
  import PackConfirmSheet from './PackConfirmSheet.svelte';
  import PackDetailSheet from './PackDetailSheet.svelte';
  import PackTakeSheet from './PackTakeSheet.svelte';
  import { providerMark } from '../../sessions/agent-marks';
  import { CELL, columns as columnsOf, conflictReason, groupCall, groupRows, reasonLabel, worstCell, type PackColumn, type SkillGroup } from './pack-model';
  import type { PackRow, PlanCall } from './pack-skills-api';
  import * as api from './pack-skills-api';
  import { data, follow, refresh } from './pack-skills.svelte';

  let { t = appT }: { t?: Translate } = $props();

  let planning = $state<PlanCall | null>(null);
  let detailOf = $state<SkillGroup | null>(null);
  let taking = $state<{ from: PackColumn; family: string; name: string } | null>(null);
  let notice = $state('');

  const view = $derived(data.view);
  const readOnly = $derived(!view || view.role !== 'alpha');
  const cols = $derived(view ? columnsOf(view) : []);
  const rows = $derived(view ? groupRows(view.rows.filter((r) => r.name.toLowerCase().includes(data.query.trim().toLowerCase()))) : []);
  const allMode = $derived(view?.choices?.mode === 'all');
  const alphaName = $derived(view?.alpha.label || t('skills.pack.alpha_unknown'));

  $effect(() => follow());

  function canTake(worst: { word: string; row: PackRow }, column: PackColumn): boolean {
    return !readOnly && !column.alpha && worst.word === 'differs' && !worst.row.warez;
  }

  async function toggleInventory(): Promise<void> {
    data.inventory = !data.inventory;
    await refresh();
  }

  async function held(rows: PackRow[], action: 'stop_syncing' | 'remove_everywhere' | 'publish_mine'): Promise<void> {
    notice = '';
    try {
      for (const row of rows) await api.postHeld(row.family, row.name, action);
      await refresh();
    } catch (error) {
      notice = t('skills.pack.failed', { reason: error instanceof Error ? error.message : String(error) });
    }
  }

  async function pushNow(): Promise<void> {
    notice = '';
    try {
      await api.syncNow();
      await refresh();
    } catch (error) {
      notice = t('skills.pack.failed', { reason: error instanceof Error ? error.message : String(error) });
    }
  }
</script>

{#snippet famMark(family: string)}
  {@const mark = providerMark(family, 14)}
  <span class="pks-fam" role="img" aria-label={mark.label} data-pks-family={family}>{@html mark.svg}</span>
{/snippet}

{#snippet nameMarks(group: SkillGroup)}
  <span class="pks-name">{#each group.rows as r (r.family)}{@render famMark(r.family)}{/each}<button type="button" class="oc-btn oc-btn--sm" data-pks-detail-open onclick={() => (detailOf = group)}>{group.name}</button></span>{#each group.rows as r (r.family)}{#if r.placed_by}<span class="lsk-col__sub" data-pks-placed-by>{t('skills.pack.placed_by', { label: r.placed_by.label })}</span>{/if}{/each}
{/snippet}

{#snippet cell(group: SkillGroup, column: PackColumn)}
  {@const worst = worstCell(view!, group, column)}
  {#if worst}
    {@const known = CELL[worst.word]}
    <span class="lsk-cell" data-state={worst.word} data-pks-cell="{group.name}|{column.id}">
      <span class="lsk-cell__mark" aria-hidden="true">{known?.mark ?? ''}</span>
      <span class="lsk-cell__word">{known ? t(`skills.pack.cell.${known.slug}`) : worst.word}</span>
      {#if worst.word === 'conflict' && conflictReason(view!, worst.row, column)}<span class="lsk-cell__folder">{reasonLabel(conflictReason(view!, worst.row, column), t)}</span>{/if}
    </span>
    {#if canTake(worst, column)}
      <button
        type="button"
        class="oc-btn oc-btn--sm"
        data-pks-take="{group.name}|{column.id}"
        aria-label={t('skills.pack.take_aria', { name: group.name, computer: column.label, alpha: alphaName })}
        onclick={() => (taking = { from: column, family: worst.row.family, name: group.name })}>{t('skills.pack.take')}</button
      >
    {/if}
  {/if}
{/snippet}

{#snippet controls(group: SkillGroup)}
  {#if group.syncable.length > 0}
    <button
      type="button"
      class="oc-btn oc-btn--sm"
      class:pks-on={group.on}
      role="switch"
      aria-checked={group.on}
      data-pks-switch={group.name}
      disabled={readOnly}
      aria-label={t(allMode ? 'skills.pack.leave_out_aria' : 'skills.pack.global_aria', { name: group.name })}
      onclick={() => (planning = groupCall(group, !group.on))}
      >{group.on ? t('skills.pack.on') : t('skills.pack.off')}</button
    >
    {#each group.held as r (r.family)}
      <span class="lsk-mark lsk-mark--warn" data-pks-held-mark={r.family}>{@render famMark(r.family)}{t('skills.pack.held_mark', { reason: r.reason || t('skills.pack.held_unknown') })}</span>
    {/each}
  {/if}
  {#if group.held.length > 0}
    <button type="button" class="oc-btn oc-btn--sm" data-pks-held="stop_syncing" disabled={readOnly} onclick={() => void held(group.held, 'stop_syncing')}>{t('skills.pack.held.stop')}</button>
    <button type="button" class="oc-btn oc-btn--sm" data-pks-held="remove_everywhere" disabled={readOnly} onclick={() => void held(group.held, 'remove_everywhere')}>{t('skills.pack.held.remove')}</button>
  {/if}
{/snippet}

<ManagerFrame
  title={t('skills.pack.title')}
  items={[]}
  status={{ kind: 'ready' }}
  query={data.query}
  onQuery={(next) => (data.query = next)}
  filters={[]}
  onFilter={() => {}}
  onClearFilters={() => {}}
  searchText={{ label: t('skills.command.search'), placeholder: t('skills.command.search') }}
  showCount={false}
  lede={t('skills.pack.lede')}
  embedded
  {t}
>
  {#snippet toolbar()}
    {#if view}<span class="lsk-mark" data-pks-alpha>{t('skills.pack.alpha_badge', { name: alphaName })}</span>{/if}
    <button
      type="button"
      class="oc-btn"
      role="switch"
      aria-checked={allMode}
      data-pks-all
      disabled={readOnly}
      class:pks-on={allMode}
      onclick={() => (planning = { kind: 'mode', mode: allMode ? 'off' : 'all' })}>{t('skills.pack.all')}: {allMode ? t('skills.pack.on') : t('skills.pack.off')}</button
    >
    <button type="button" class="oc-btn" role="switch" aria-checked={data.inventory} class:pks-on={data.inventory} data-pks-inventory disabled={readOnly} onclick={() => void toggleInventory()}>{t('skills.pack.inventory')}</button>
    <button type="button" class="oc-btn" data-pks-sync-now onclick={() => void pushNow()}>{t('skills.pack.sync_now')}</button>
  {/snippet}
  {#snippet body()}
    <div class="lsk-page" data-pks>
      {#if readOnly && view}<p class="lsk-line" role="status" data-pks-readonly>{t('skills.pack.read_only', { name: alphaName })}</p>{/if}
      {#if data.status === 'error'}<p class="lsk-line lsk-line--error" role="alert" data-pks-error>{t('skills.pack.read_failed', { reason: data.error })}</p>{/if}
      {#if notice}<p class="lsk-line lsk-line--warn" role="alert" data-pks-notice>{notice}</p>{/if}
      {#if view?.problem}<p class="lsk-line lsk-line--warn" data-pks-problem>{view.problem}</p>{/if}
      {#if view?.hold}
        <p class="lsk-line lsk-line--warn" data-pks-hold>{t('skills.pack.hold')}</p>
        {#if view.rows[0] && !readOnly}
          <button type="button" class="oc-btn oc-btn--sm" data-pks-publish-mine onclick={() => void held([view.rows[0]!], 'publish_mine')}>{t('skills.pack.publish_mine')}</button>
        {/if}
      {/if}
      {#if data.status === 'loading'}
        <p class="lsk-line" role="status">{t('skills.command.loading')}</p>
      {:else if view && view.rows.length === 0}
        <p class="lsk-line" role="status" data-pks-empty>{t('skills.pack.empty')}</p>
      {:else if view && viewport.narrow}
        <ul class="lsk-list" aria-label={t('skills.pack.list')} data-pks-list>
          {#each rows as row (row.name)}
            <li class="lsk-item" data-pks-row={row.name}>
              <div class="lsk-item__head">
                {@render nameMarks(row)}
                <span class="pks-controls">{@render controls(row)}</span>
              </div>
              <ul class="lsk-places">
                {#each cols as column (column.id)}
                  <li class="lsk-place"><span class="lsk-place__label">{column.label}</span>{@render cell(row, column)}</li>
                {/each}
              </ul>
            </li>
          {/each}
        </ul>
      {:else if view}
        <div class="lsk-scroll lsk-scroll--pack" data-pks-matrix>
          <table class="lsk-table">
            <thead class="pks-head">
              <tr>
                <th scope="col" class="lsk-table__name">{t('skills.command.col.skill')}</th>
                <th scope="col">{t(allMode ? 'skills.pack.col_leave_out' : 'skills.pack.col_global')}</th>
                {#each cols as column (column.id)}
                  <th scope="col" data-pks-col={column.id}>
                    <span class="lsk-col__label">{column.label}</span>
                    {#if column.alpha}<span class="lsk-col__sub">{t('skills.pack.alpha_col')}</span>{/if}
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each rows as row (row.name)}
                <tr data-pks-row={row.name}>
                  <th scope="row" class="lsk-table__name">{@render nameMarks(row)}</th>
                  <td><span class="pks-controls">{@render controls(row)}</span></td>
                  {#each cols as column (column.id)}
                    <td>{@render cell(row, column)}</td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  {/snippet}
</ManagerFrame>

{#if planning}
  <PackConfirmSheet call={planning} onDone={refresh} onClose={() => (planning = null)} {t} />
{/if}
{#if taking}
  <PackTakeSheet from={taking.from} family={taking.family} name={taking.name} alpha={alphaName} onDone={refresh} onClose={() => (taking = null)} {t} />
{/if}
{#if detailOf}
  <PackDetailSheet families={detailOf.rows.map((r) => r.family)} name={detailOf.name} placedBy={detailOf.rows.find((r) => r.placed_by)?.placed_by?.label} onClose={() => (detailOf = null)} {t} />
{/if}

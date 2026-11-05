
<script lang="ts">
  import { onMount } from 'svelte';
  import '../session-move/move-folder.css';
  import '../send-to/send-to.css';
  import { t } from '../i18n/index.svelte';
  import ModalShell from '../dialog-frame/ModalShell.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import Button from '../base/Button.svelte';
  import { applyCleanup, planCleanup, type CleanupPlan, type CleanupResult, type CleanupScope } from './api';

  interface Props { scope: CleanupScope; close: (value: { removed: number } | null) => void }
  const { scope, close }: Props = $props();

  let plan = $state<CleanupPlan | null>(null);
  let error = $state('');
  let busy = $state(false);
  let deleteUnmerged = $state(false);
  let removeDirty = $state(false);
  let results = $state<CleanupResult[] | null>(null);

  const anyUnmerged = $derived(!!plan?.worktrees.some((w) => !w.merged && w.unmerged_commits > 0));
  const anyDirty = $derived(!!plan?.worktrees.some((w) => w.dirty.length > 0));

  async function read(): Promise<void> {
    error = ''; plan = null;
    try { plan = await planCleanup(scope); } catch (err) { error = err instanceof Error ? err.message : String(err); }
  }

  onMount(() => { void read(); });

  async function go(): Promise<void> {
    if (!plan || busy) return;
    busy = true; error = '';
    try {
      results = (await applyCleanup(plan, deleteUnmerged, removeDirty)).removed;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      await read();
    }
    busy = false;
  }

  const title = $derived(scope.finishedOnly ? t('worktree.cleanup.title_finished') : t('worktree.cleanup.title'));
</script>

<ModalShell {title} overlayClass="stm-modal" contentClass="stm popup-focus" dismissable={!busy}
  onCancel={() => close(null)} data-worktree-cleanup="">
  {#snippet head()}
    <div class="stm-titlerow">
      <span class="stm-label">{t('worktree.cleanup.label')}</span>
      <span class="stm-title">{title}</span>
    </div>
  {/snippet}
  <div class="stm-body">
    {#if results}
      {#each results as r (r.path)}
        <p class={r.removed ? 'stm-note' : 'stm-error'} data-wtc-result={r.removed ? 'removed' : 'kept'}>
          {r.removed ? t(r.branch_deleted ? 'worktree.cleanup.removed_branch' : 'worktree.cleanup.removed', { path: r.path }) : t('worktree.cleanup.kept', { path: r.path, why: r.error ?? '' })}
        </p>
      {/each}
    {:else if !plan && !error}
      <p class="stm-note">{t('worktree.cleanup.checking')}</p>
    {:else if plan && plan.worktrees.length === 0}
      <p class="stm-note" data-wtc="none">{t('worktree.cleanup.none')}</p>
    {:else if plan}
      {#each plan.worktrees as w (w.path)}
        <div class="mvf-plan" data-wtc-item={w.path}>
          <div class="mvf-plan-row"><span class="mvf-plan-key">{t('worktree.cleanup.path')}</span><span class="mvf-plan-val">{w.path}{w.exists ? '' : ` (${t('worktree.cleanup.gone')})`}</span></div>
          <div class="mvf-plan-row"><span class="mvf-plan-key">{t('worktree.cleanup.branch')}</span><span class="mvf-plan-val">{w.branch} &middot; {w.merged ? t('worktree.cleanup.merged', { base: w.base_branch }) : t('worktree.cleanup.unmerged', { count: String(w.unmerged_commits), base: w.base_branch })} &middot; {t(w.pushed ? 'worktree.cleanup.pushed' : 'worktree.cleanup.not_pushed')}</span></div>
          {#if w.dirty.length}
            <div class="mvf-plan-row" data-wtc-dirty><span class="mvf-plan-key">{t('worktree.cleanup.dirty', { count: String(w.dirty.length), untracked: String(w.untracked) })}</span><span class="mvf-plan-val mvf-bad">{w.dirty.join(', ')}</span></div>
          {/if}
          <div class="mvf-plan-row"><span class="mvf-plan-key">{t('worktree.cleanup.steps')}</span><span class="mvf-plan-val">{w.steps.join('; ')}</span></div>
        </div>
      {/each}
      {#if anyUnmerged}
        <Check label={t('worktree.cleanup.delete_unmerged')} checked={deleteUnmerged} disabled={busy} data-wtc="delete-unmerged" onToggle={(next) => (deleteUnmerged = next)} />
      {/if}
      {#if anyDirty}
        <p class="stm-option-why">{t('worktree.cleanup.dirty_hint')}</p>
        <Check label={t('worktree.cleanup.remove_dirty')} checked={removeDirty} disabled={busy} data-wtc="remove-dirty" onToggle={(next) => (removeDirty = next)} />
      {/if}
    {/if}
    {#if error}<p class="stm-error" role="alert" data-wtc="error">{error}</p>{/if}
  </div>
  {#snippet footer()}
    <footer class="stm-foot">
      {#if results}
        <Button variant="confirm" data-wtc="close" onclick={() => close({ removed: results?.filter((r) => r.removed).length ?? 0 })}>{t('worktree.cleanup.close')}</Button>
      {:else}
        <Button data-wtc="cancel" disabled={busy} onclick={() => close(null)}>{t('worktree.cleanup.cancel')}</Button>
        <Button variant="danger" data-wtc="go" disabled={busy || !plan || plan.worktrees.length === 0} onclick={() => void go()}>{t('worktree.cleanup.go')}</Button>
      {/if}
    </footer>
  {/snippet}
</ModalShell>

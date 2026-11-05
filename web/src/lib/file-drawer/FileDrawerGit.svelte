<script lang="ts">
  import { Button, List, ListRow } from '../base';
  import Select from '../base/Select.svelte';
  import Tabs, { panelAttrs } from '../../opscenter/ui/Tabs.svelte';
  import { mountDiffInto } from '../../opscenter/cells/terminal-live/mount-diff';
  import { workdirRelative } from '../open-files/paths';
  import { sessionGit, releaseSessionGit } from '../../opscenter/api/session-git.svelte';
  import type { Resource } from '../../opscenter/api/poll.svelte';
  import type { SessionGitFile, SessionGitStatus } from '../../opscenter/api/types';
  import { sessionCheckpoints, releaseSessionCheckpoints } from '../../opscenter/api/session-checkpoints.svelte';
  import { checkpointDiffPath, fetchCheckpointChanges, turnClock, type Checkpoint, type CheckpointList } from '../checkpoints/api';
  import RevertConfirm from '../checkpoints/RevertConfirm.svelte';
  import { openModal } from '../modal';
  import { t } from '../i18n/index.svelte';
  import { drawerGit, selectDrawerTab, type FileDrawerTab } from './git-view.svelte';
  import { applyGitTags, buildGitTags, GIT_LETTERS, GIT_TONES } from './git-tags';

  interface Props {
    tree?: HTMLElement | null;
    onTab?: (tab: FileDrawerTab) => void;
    onOpenDiff?: (path: string, mountView: (body: HTMLElement) => () => void) => void;
    onOpenFile?: (path: string, repoRoot: string, workdirPath: string | null) => void;
  }

  let { tree = null, onTab = () => {}, onOpenDiff = () => {}, onOpenFile = () => {} }: Props = $props();

  let res = $state<Resource<SessionGitStatus> | null>(null);

  $effect(() => {
    const id = drawerGit.sessionId;
    if (!id) { res = null; return; }
    res = sessionGit(id);
    return () => releaseSessionGit(id);
  });

  const data = $derived(res?.data ?? null);
  const view = $derived<'loading' | 'unknown' | 'clean' | 'list' | 'not_a_repo' | 'remote'>(
    !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading')
      : data.state === 'ok' ? (data.files.length + data.truncated === 0 ? 'clean' : 'list')
      : data.state,
  );
  const shownTab = $derived<FileDrawerTab>(drawerGit.sessionId ? drawerGit.tab : 'files');
  const total = $derived(data?.state === 'ok' ? data.files.length + data.truncated : null);

  $effect(() => { onTab(shownTab); });

  const index = $derived(
    data?.state === 'ok' && data.repo_root && drawerGit.workdir
      ? buildGitTags(data.files, data.repo_root, data.working_dir_real || drawerGit.workdir)
      : null,
  );

  $effect(() => {
    const el = tree;
    const idx = index;
    if (!el) return;
    applyGitTags(el, idx);
    if (!idx || typeof MutationObserver === 'undefined') return;
    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; applyGitTags(el, idx); });
    });
    observer.observe(el, { childList: true, subtree: true });
    return () => observer.disconnect();
  });

  let turnsRes = $state<Resource<CheckpointList> | null>(null);
  $effect(() => {
    const rowId = drawerGit.rowId;
    if (rowId === null || shownTab !== 'changed' || view === 'remote' || view === 'not_a_repo') { turnsRes = null; return; }
    turnsRes = sessionCheckpoints(rowId);
    return () => releaseSessionCheckpoints(rowId);
  });
  const turns = $derived<Checkpoint[]>((turnsRes?.data?.checkpoints ?? []).filter((c) => c.kind === 'turn' || c.kind === 'safety'));

  let turn = $state('now');
  $effect(() => { void drawerGit.sessionId; turn = 'now'; });
  const picked = $derived<Checkpoint | null>(turn === 'now' ? null : turns.find((c) => String(c.id) === turn) ?? null);
  $effect(() => { if (turn !== 'now' && turnsRes?.data && !picked) turn = 'now'; });

  let turnFiles = $state<SessionGitFile[] | null>(null);
  let turnFailed = $state(false);
  $effect(() => {
    const rowId = drawerGit.rowId;
    const cp = picked;
    turnFiles = null;
    turnFailed = false;
    if (rowId === null || !cp) return;
    let live = true;
    fetchCheckpointChanges(rowId, cp.id).then(
      (r) => { if (live) turnFiles = r.files; },
      () => { if (live) turnFailed = true; },
    );
    return () => { live = false; };
  });
  const turnView = $derived<'loading' | 'unknown' | 'empty' | 'list'>(
    turnFailed ? 'unknown' : !turnFiles ? 'loading' : turnFiles.length === 0 ? 'empty' : 'list',
  );

  function turnLabel(cp: Checkpoint): string {
    const key = cp.kind === 'safety' ? 'files.drawer.turn_safety' : cp.pinned ? 'files.drawer.turn_pinned' : 'files.drawer.turn';
    return t(key, { time: turnClock(cp.created_at) });
  }

  async function openRevert(cp: Checkpoint): Promise<void> {
    const rowId = drawerGit.rowId;
    if (rowId === null) return;
    const done = await openModal(RevertConfirm, { rowId, checkpoint: cp });
    if (done) turn = 'now';
  }

  function openDiff(path: string): void {
    const sessionId = drawerGit.sessionId;
    const rowId = drawerGit.rowId;
    const source = picked && rowId !== null ? checkpointDiffPath(rowId, picked.id, path) : '';
    onOpenDiff(path, (body) => mountDiffInto(body, { sessionId, path, source }));
  }
</script>

{#if drawerGit.sessionId}
  <div class="fdg" data-file-git="" data-tab={shownTab}>
    <Tabs
      tabs={[
        { id: 'files', label: t('files.drawer.tab.files') },
        { id: 'changed', label: t('files.drawer.tab.changed'), badge: total },
      ]}
      active={shownTab}
      onSelect={(id) => selectDrawerTab(id === 'changed' ? 'changed' : 'files')}
      label={t('files.drawer.tabs')}
      idBase="fdg"
    />
    {#if shownTab === 'changed'}
      <div class="fdg-panel" {...panelAttrs('fdg', 'changed')} data-git-changes="" data-view={view}>
        {#if turns.length > 0}
          <div class="fdg-turn" data-git-turns="">
            <Select size="sm" aria-label={t('files.drawer.turn_pick')} data-git-turn-pick="" bind:value={turn}
              options={[{ value: 'now', label: t('files.drawer.turn_now') }, ...turns.map((c) => ({ value: String(c.id), label: turnLabel(c) }))]} />
          </div>
        {/if}
        {#if picked}
          <div class="fdg-revert">
            <Button variant="quiet" size="sm" data-git-revert="" onclick={() => openRevert(picked)}>{t('files.drawer.turn_revert')}</Button>
          </div>
          {#if picked.left_out.length > 0}<p class="fdg-note" data-git-left-out="">{t('files.drawer.turn_left_out', { n: picked.left_out.length })}</p>{/if}
          {#if turnView === 'list' && turnFiles}
            {@render rows(turnFiles, 0)}
          {:else}
            <p class="fdg-note" data-git-note={`turn_${turnView}`} role="status">{t(`files.drawer.turn_${turnView}`)}</p>
          {/if}
        {:else if view === 'list' && data}
          {@render rows(data.files, data.truncated)}
        {:else}
          <p class="fdg-note" data-git-note={view} role="status">{t(`git.changes.${view}`)}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}

{#snippet rows(files: SessionGitFile[], more: number)}
          <List label={t('git.changes.list')}>
            {#each files as file (file.path + ':' + file.index + file.worktree)}
              <ListRow data-git-row="" data-kind={file.kind} data-git-tone={GIT_TONES[file.kind]}
                title={file.orig_path ? t('git.changes.renamed_from', { path: file.orig_path }) : file.path}>
                {#snippet primary()}
                  <Button variant="row" data-git-diff={file.path} onclick={() => openDiff(file.path)}>
                    <bdi class="fdg-path" data-git-path="">{file.path}</bdi>
                    {#if file.submodule}<span class="fdg-tag">{t('git.changes.submodule')}</span>{/if}
                    <span class="fdg-letter" data-git-letter={GIT_LETTERS[file.kind]}
                      aria-label={t(`git.changes.kind.${file.kind}`)}>{GIT_LETTERS[file.kind]}</span>
                  </Button>
                {/snippet}
                {#snippet actions()}
                  {#if file.kind !== 'deleted' && data?.repo_root}
                    <Button variant="quiet" size="sm" data-git-open={file.path}
                      aria-label={t('git.changes.open_file', { path: file.path })}
                      onclick={() => onOpenFile(file.path, data?.repo_root ?? '', workdirRelative(file.path, data?.repo_root ?? '', data?.working_dir_real))}>{t('git.changes.open_file_short')}</Button>
                  {/if}
                {/snippet}
              </ListRow>
            {/each}
            {#if more > 0}<ListRow class="fdg-more" data-git-more="" primary={t('git.changes.more', { n: more })} />{/if}
          </List>
{/snippet}

<style>
  @layer components {
    .fdg { display:flex; flex-direction:column; flex:1 1 auto; min-height:0; font-family:var(--font-mono); font-size:12px; color:var(--oc-text-secondary); }

    .fdg-panel { flex:1 1 auto; min-height:0; overflow-y:auto; padding:4px 4px 8px; }

    .fdg-panel:focus-visible { outline:none; box-shadow:inset 0 0 0 1px var(--oc-orange); }

    .fdg-panel :global([data-git-diff]) { flex:1 1 auto; min-width:0; flex-wrap:nowrap; padding:0 6px 0 4px; font:inherit; color:inherit; }

    .fdg-path { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

    .fdg-letter { flex:0 0 auto; min-width:1em; text-align:right; }

    .fdg-panel :global([data-git-tone='green'] :is([data-git-path], [data-git-letter])) { color:var(--oc-green); }

    .fdg-panel :global([data-git-tone='yellow'] :is([data-git-path], [data-git-letter])) { color:var(--oc-yellow); }

    .fdg-panel :global([data-git-tone='coral'] :is([data-git-path], [data-git-letter])) { color:var(--oc-coral); }

    .fdg-tag { flex:0 0 auto; color:var(--oc-text-dim); }

    .fdg-turn { padding-bottom:var(--oc-space-1); margin-bottom:var(--oc-space-1); box-shadow:0 1px 0 var(--oc-line-rule); }

    .fdg-turn :global(select) { width:100%; }
    .fdg-revert { display:flex; justify-content:flex-end; margin-bottom:var(--oc-space-1); }

    .fdg-note, .fdg-panel :global(.fdg-more) { margin:0; padding:var(--oc-space-1) 6px; color:var(--oc-text-dim); }

    .fdg-note[data-git-note='unknown'] { color:var(--oc-coral); }
  }
</style>

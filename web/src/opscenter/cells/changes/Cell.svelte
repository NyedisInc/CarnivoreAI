<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const CHANGES_WIDGET = defineWidget({ id: 'core.changes', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  import { mount, unmount } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import GitDiffView from '../terminal-live/GitDiffView.svelte';
  import { sessionGit, releaseSessionGit } from '../../api/session-git.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { SessionGitFile, SessionGitStatus } from '../../api/types';
  import { activeTerminalSessionId } from '../../lib/active-terminal';
  import { t } from '../../../lib/i18n/index.svelte';
  import { Button, List, ListRow, Tag } from '../../../lib/base';
  import { GIT_LETTERS, GIT_TONES } from '../../../lib/file-drawer/git-tags';
  import { openAsRow, openDiff, openFile, placementFor } from './openers';
  import { workdirRelative } from '../../../lib/open-files/paths';
  import { railSlideout } from '../../../lib/session-rail/slideout.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';

  let props: CellProps = $props();

  const widget = useWidget(CHANGES_WIDGET, () => props);
  const sessionId = $derived(widget.sessionId);

  let res = $state<Resource<SessionGitStatus> | null>(null);

  $effect(() => {
    const id = sessionId;
    if (!id) { res = null; return; }
    res = sessionGit(id);
    return () => releaseSessionGit(id);
  });

  const data = $derived(res?.data ?? null);
  const view = $derived<'none' | 'loading' | 'unknown' | 'clean' | 'list' | 'not_a_repo' | 'remote'>(
    !sessionId ? 'none'
      : !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading')
      : data.state === 'ok' ? (data.files.length + data.truncated === 0 ? 'clean' : 'list')
      : data.state,
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = {
    list: 'ready', none: 'none', loading: 'loading', unknown: 'error', clean: 'empty', not_a_repo: 'none', remote: 'none',
  };
  const note = $derived(t(view === 'none' ? 'opscenter.cell.changes.no_session' : `git.changes.${view}`));

  /* the page terminal */
  function placement() {
    const id = sessionId;
    return placementFor(() => activeTerminalSessionId() === id, () => railSlideout.open('core.changes'));
  }

  async function showDiff(path: string): Promise<void> {
    const id = sessionId;
    if (!id) return;
    if (await openAsRow(id, { path, kind: 'diff' }) !== 'unavailable') return;
    openDiff(path, t('git.diff.subtitle'), (body) => {
      const shown = mount(GitDiffView, { target: body, props: { sessionId: id, path } });
      return () => { void unmount(shown); };
    }, placement());
  }

  async function showFile(file: SessionGitFile, status: SessionGitStatus): Promise<void> {
    const id = sessionId;
    if (!id) return;
    const rowPath = workdirRelative(file.path, status.repo_root, status.working_dir_real);
    if (rowPath && await openAsRow(id, { path: rowPath, kind: 'file' }) !== 'unavailable') return;
    openFile(file.path, status.repo_root ?? '', placement());
  }
</script>

<WidgetShell {widget} status={STATUS[view]} {note}>
  <div class="oc-chg" data-changes-cell data-view={view} data-session={sessionId || undefined}>
    {#if data && view === 'list'}
      <List density="dense" label={t('git.changes.list')}>
        {#snippet children()}
          {#each data.files as file (file.path + ':' + file.index + file.worktree)}
            <ListRow density="dense" data-kind={file.kind} data-git-tone={GIT_TONES[file.kind]}
              title={file.orig_path ? t('git.changes.renamed_from', { path: file.orig_path }) : file.path}>
              {#snippet children()}
                <Button variant="row" data-git-diff={file.path} onclick={() => void showDiff(file.path)}>
                  <bdi class="oc-chg-path">{file.path}</bdi>
                  {#if file.submodule}<Tag>{t('git.changes.submodule')}</Tag>{/if}
                  <span class="oc-chg-letter" data-git-letter={GIT_LETTERS[file.kind]}
                    aria-label={t(`git.changes.kind.${file.kind}`)}>{GIT_LETTERS[file.kind]}</span>
                </Button>
              {/snippet}
              {#snippet actions()}
                {#if file.kind !== 'deleted' && data.repo_root}
                  <Button variant="quiet" size="sm" data-git-open={file.path} aria-label={t('git.changes.open_file', { path: file.path })}
                    onclick={() => void showFile(file, data)}>{t('git.changes.open_file_short')}</Button>
                {/if}
              {/snippet}
            </ListRow>
          {/each}
          {#if data.truncated > 0}<ListRow density="dense" data-git-more="" primary={t('git.changes.more', { n: data.truncated })} />{/if}
        {/snippet}
      </List>
    {/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-chg { height: 100%; min-height: 0; overflow-y: auto; padding: var(--oc-space-1) var(--oc-space-1) var(--oc-space-2); font-family: var(--font-mono); font-size: var(--oc-fs-body); }

    :global(.oc-list__row[data-git-tone] > [data-git-diff]) { flex: 1 1 auto; min-width: 0; }

    .oc-chg-path { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .oc-chg-letter { flex: 0 0 auto; min-width: 1em; text-align: right; }

    :global(.oc-list__row[data-git-tone='green']) :is(.oc-chg-path, .oc-chg-letter) { color: var(--oc-green); }

    :global(.oc-list__row[data-git-tone='yellow']) :is(.oc-chg-path, .oc-chg-letter) { color: var(--oc-yellow); }

    :global(.oc-list__row[data-git-tone='coral']) :is(.oc-chg-path, .oc-chg-letter) { color: var(--oc-coral); }

  }
</style>

<script lang="ts">
  import { mount, unmount } from 'svelte';
  import { Button, List, ListRow } from '../base';
  import Tabs, { panelAttrs } from '../../opscenter/ui/Tabs.svelte';
  import GitDiffView from '../../opscenter/cells/terminal-live/GitDiffView.svelte';
  import { workdirRelative } from '../open-files/paths';
  import { sessionGit, releaseSessionGit } from '../../opscenter/api/session-git.svelte';
  import type { Resource } from '../../opscenter/api/poll.svelte';
  import type { SessionGitStatus } from '../../opscenter/api/types';
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

  function openDiff(path: string): void {
    const sessionId = drawerGit.sessionId;
    onOpenDiff(path, (body) => {
      const shown = mount(GitDiffView, { target: body, props: { sessionId, path } });
      return () => { void unmount(shown); };
    });
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
        {#if view === 'list' && data}
          <List label={t('git.changes.list')}>
            {#each data.files as file (file.path + ':' + file.index + file.worktree)}
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
                  {#if file.kind !== 'deleted' && data.repo_root}
                    <Button variant="quiet" size="sm" data-git-open={file.path}
                      aria-label={t('git.changes.open_file', { path: file.path })}
                      onclick={() => onOpenFile(file.path, data.repo_root ?? '', workdirRelative(file.path, data.repo_root, data.working_dir_real))}>{t('git.changes.open_file_short')}</Button>
                  {/if}
                {/snippet}
              </ListRow>
            {/each}
            {#if data.truncated > 0}<ListRow class="fdg-more" data-git-more="" primary={t('git.changes.more', { n: data.truncated })} />{/if}
          </List>
        {:else}
          <p class="fdg-note" data-git-note={view} role="status">{t(`git.changes.${view}`)}</p>
        {/if}
      </div>
    {/if}
  </div>
{/if}

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

    .fdg-note, .fdg-panel :global(.fdg-more) { margin:0; padding:var(--oc-space-1) 6px; color:var(--oc-text-dim); }

    .fdg-note[data-git-note='unknown'] { color:var(--oc-coral); }
  }
</style>

<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  import type { TopFolder } from '../../../lib/file-drawer/roots-prefs.svelte';
  import { FILES_STATE } from './state';

  export const FILES_WIDGET = defineWidget({
    id: 'core.files',
    scope: 'session',
    actions: [
      { id: 'search', labelKey: 'opscenter.cell.files.menu.filter', group: 'view' },
      { id: 'just-changes', labelKey: 'opscenter.cell.files.menu.just_changes', kind: 'switch', group: 'view' },
      { id: 'whole-file', labelKey: 'opscenter.cell.files.menu.whole_file', kind: 'switch', group: 'view' },
      { id: 'show-global-folder', labelKey: 'widgets.setting.files.show_global_folder', kind: 'switch', group: 'show' },
      { id: 'list-project-first', labelKey: 'opscenter.cell.files.menu.project_first', kind: 'switch', group: 'show' },
      { id: 'include-dot-files', labelKey: 'opscenter.cell.files.menu.dot_files', kind: 'switch', group: 'show' },
      { id: 'git-ignored-files', labelKey: 'opscenter.cell.files.menu.ignored', kind: 'switch', group: 'show' },
      { id: 'collapse-all', labelKey: 'opscenter.cell.files.menu.collapse', group: 'tree' },
      { id: 'reload', labelKey: 'opscenter.cell.files.menu.reload', group: 'tree' },
    ],
    settings: { showGlobalFolder: true as boolean, topFolder: 'global' as TopFolder },
    state: FILES_STATE,
  });
</script>

<script lang="ts">
  /*  hidden
 */
  import { tick, untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api/sessions.svelte';
  import { sessionGit, releaseSessionGit } from '../../api/session-git.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { SessionGitStatus } from '../../api/types';
  import { titlelessHost } from '../../shell/frame-header.svelte';
  import { useWidget, type WidgetHandle } from '../../widgets/shell/define-widget.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { buildGitTags, gitTagFor, GIT_LETTERS, GIT_TONES, type GitTag } from '../../../lib/file-drawer/git-tags';
  import { writeRootPrefs } from '../../../lib/file-drawer/roots-prefs.svelte';
  import { findIn, openInFilesList, readLevel } from '../../../lib/file-drawer/tree-api';
  import { workdirRelative } from '../../../lib/open-files/paths';
  import { t } from '../../../lib/i18n/index.svelte';
  import { buildRows, focusable, levelKey, parentOf, rootOrder, splitLevelKey, stepFocus, unreadLevels, type FxRow, type Level, type RootId } from './model';
  import { fk, GLOBAL_PATH, labelOf, subOf, titleOf } from './labels';
  import { FILTER_MAX, foldScope, sectionIsOpen, withFold, withoutScopes } from './state';
  import { watchOnScreen } from './on-screen';
  import FileRow from './FileRow.svelte';
  import FilesFilter from './FilesFilter.svelte';
  import ProjectGit from './ProjectGit.svelte';

  let props: CellProps = $props();

  const CHANGES_CAP = 5;
  const FILTER_DEBOUNCE_MS = 200;

  const widget: WidgetHandle<typeof FILES_WIDGET> = useWidget(FILES_WIDGET, () => props, () => ({
    search: { run: () => filterEl?.focus() },
    'just-changes': { on: justChanges, run: toggleJustChanges, blocked: changeCount === 0 && !justChanges ? fk('changed.none_reason') : '' },
    'whole-file': { on: view['whole-file'], run: () => (view['whole-file'] = !view['whole-file']) },
    'show-global-folder': { on: showGlobal, run: () => void setRoots({ showGlobalFolder: !showGlobal }) },
    'list-project-first': {
      on: topFolder === 'project', blocked: showGlobal ? '' : fk('menu.project_first_reason'),
      run: () => void setRoots({ topFolder: topFolder === 'project' ? 'global' : 'project' }),
    },
    'include-dot-files': { on: view['dot-files'], run: () => (view['dot-files'] = !view['dot-files']) },
    'git-ignored-files': { on: view['ignored-files'], run: () => (view['ignored-files'] = !view['ignored-files']) },
    'collapse-all': { run: collapseAll },
    reload: { run: reload },
  }));
  const view = widget.state;

  const sessionId = $derived(widget.sessionId);
  const showGlobal = $derived(widget.setting('showGlobalFolder'));
  const topFolder = $derived<TopFolder>(widget.setting('topFolder') === 'project' ? 'project' : 'global');
  const justChanges = $derived(view['just-changes']);
  const narrow = $derived(widget.widthState === 'narrow');
  const headerDrawn = $derived(!!widget.frame?.drawn);
  const corner = titlelessHost();

  let rootEl = $state<HTMLDivElement | null>(null);
  let onScreen = $state(false);
  $effect(() => (rootEl ? watchOnScreen(rootEl, (yes) => (onScreen = yes)) : undefined));

  let gitRes = $state.raw<Resource<SessionGitStatus> | null>(null);
  $effect(() => {
    const id = sessionId;
    if (!id || !onScreen) return;
    const held = sessionGit(id);
    gitRes = held;
    return () => {
      releaseSessionGit(id);
      if (gitRes === held) gitRes = null;
    };
  });
  const git = $derived(gitRes?.data ?? null);
  const gitOk = $derived(git?.state === 'ok' ? git : null);

  const workdir = $derived.by(() => {
    if (!sessionId) return '';
    const row = (sessions.data ?? []).find((info) => info.session?.id === sessionId);
    const scoped = props.scope?.sessionId === sessionId ? props.scope.workingDir : '';
    return row?.session?.working_dir || scoped || gitOk?.working_dir_real || '';
  });
  const projectName = $derived(gitOk?.repo_name || workdir.split('/').filter(Boolean).pop() || '');
  const projectScope = $derived(foldScope('workdir', workdir));

  let levels = $state<Record<string, Level>>({});
  let generation = 0;

  async function load(root: RootId, path: string): Promise<void> {
    const key = levelKey(root, path);
    const asked = generation;
    const folder = workdir || null;
    levels[key] = { status: 'loading', nodes: levels[key]?.nodes ?? [], error: null };
    try {
      const answer = await readLevel(root, folder, path);
      if (asked === generation) levels[key] = { status: 'ready', nodes: answer.tree ?? [], error: null };
    } catch (err) {
      if (asked === generation) levels[key] = { status: 'error', nodes: [], error: err instanceof Error ? err.message : String(err) };
    }
  }

  $effect(() => {
    void workdir;
    untrack(() => {
      generation += 1;
      for (const key of Object.keys(levels)) if (key.startsWith('workdir:')) delete levels[key];
    });
  });

  const expanded = $derived(new Set([
    ...(view.folds['user'] ?? []).map((path) => levelKey('user', path)),
    ...(workdir ? (view.folds[projectScope] ?? []) : []).map((path) => levelKey('workdir', path)),
  ]));

  let search = $state<Record<RootId, Level & { truncated: boolean }> | null>(null);
  let filterEl = $state<HTMLInputElement | null>(null);
  const query = $derived(view.filter.trim());
  $effect(() => {
    const q = query;
    const folder = workdir || null;
    const withGlobal = showGlobal;
    if (!q) { search = null; return; }
    if (!onScreen) return;
    const timer = setTimeout(() => {
      const pending: Level & { truncated: boolean } = { status: 'loading', nodes: [], error: null, truncated: false };
      search = { workdir: { ...pending }, user: { ...pending } };
      for (const root of ['workdir', 'user'] as const) {
        if ((root === 'workdir' && !folder) || (root === 'user' && !withGlobal)) continue;
        findIn(root, folder, q).then(
          (answer) => { if (search && query === q) search[root] = { status: 'ready', nodes: answer.tree ?? [], error: null, truncated: !!answer.truncated }; },
          (err) => { if (search && query === q) search[root] = { status: 'error', nodes: [], error: err instanceof Error ? err.message : String(err), truncated: false }; },
        );
      }
    }, FILTER_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  });

  const changeCount = $derived(gitOk ? gitOk.files.length + gitOk.truncated : 0);
  const tags = $derived(gitOk?.repo_root && workdir ? buildGitTags(gitOk.files, gitOk.repo_root, gitOk.working_dir_real || workdir) : null);
  const rows = $derived(buildRows({
    roots: justChanges ? ['workdir'] : rootOrder(showGlobal, topFolder),
    sectionOpen: justChanges
      ? { workdir: true, user: false }
      : { workdir: sectionIsOpen(view.sections, 'workdir', !!workdir), user: sectionIsOpen(view.sections, 'user', !!workdir) },
    levels,
    expanded,
    options: { showDot: view['dot-files'], showIgnored: view['ignored-files'] },
    hasProject: !!workdir,
    changes: gitOk ? gitOk.files : null,
    changesTruncated: gitOk?.truncated ?? 0,
    changesOpen: view['changes-open'],
    changedOnly: justChanges,
    changesCap: CHANGES_CAP,
    search,
  }));

  $effect(() => {
    if (!onScreen) return;
    for (const key of unreadLevels(rows)) untrack(() => void load(...splitLevelKey(key)));
  });

  function tagOf(row: FxRow): GitTag | null {
    if (row.kind === 'change') return { letter: GIT_LETTERS[row.file.kind], tone: GIT_TONES[row.file.kind], kind: row.file.kind };
    if (row.kind === 'node' && row.root === 'workdir' && tags && row.node.rel_path) return gitTagFor(tags, row.node.rel_path, row.node.is_dir);
    return null;
  }

  let status = $state<{ text: string; tone: 'muted' | 'error' } | null>(null);

  function say(text: string, tone: 'muted' | 'error' = 'muted'): void {
    status = { text, tone };
  }

  async function openRow(root: RootId, path: string, kind: 'file' | 'diff', name: string): Promise<void> {
    const result = await openInFilesList(sessionId, root, path, kind);
    if (result === 'opened') say(fk('open.opened', { name }));
    else if (result === 'unavailable') say(fk('open.no_session'), 'error');
    else say(fk('open.refused'), 'error');
  }

  function toggleJustChanges(): void {
    view['just-changes'] = !view['just-changes'];
  }

  function setOpen(row: FxRow, open?: boolean): void {
    if (row.kind === 'section') view.sections = { ...view.sections, [row.root]: open ?? !row.open };
    else if (row.kind === 'group') view['changes-open'] = open ?? !row.open;
    else if (row.kind === 'node' && row.node.is_dir && !search) {
      const next = open ?? !row.open;
      view.folds = withFold(view.folds, foldScope(row.root, workdir), row.node.rel_path, next);
      if (next && levels[levelKey(row.root, row.node.rel_path)]?.status === 'error') void load(row.root, row.node.rel_path);
    }
  }

  function activate(row: FxRow, alt: boolean): void {
    if (row.kind === 'section' || row.kind === 'group') setOpen(row);
    else if (row.kind === 'more') view['just-changes'] = true;
    else if (row.kind === 'note' && row.retry) void load(...splitLevelKey(row.retry));
    else if (row.kind === 'node') {
      if (row.node.is_dir) setOpen(row);
      else void openRow(row.root, row.node.rel_path, 'file', row.node.name);
    } else if (row.kind === 'change') {
      const name = labelOf(row, query);
      if (view['whole-file'] === alt) { void openRow('workdir', row.file.path, 'diff', name); return; }
      const path = workdirRelative(row.file.path, gitOk?.repo_root, gitOk?.working_dir_real);
      if (row.file.kind === 'deleted') say(fk('open.deleted'), 'error');
      else if (!path) say(fk('open.outside'), 'error');
      else void openRow('workdir', path, 'file', name);
    }
  }

  function reload(): void {
    for (const key of Object.keys(levels)) void load(...splitLevelKey(key));
    void gitRes?.refresh(true);
  }

  function collapseAll(): void {
    view.folds = withoutScopes(view.folds, ['user', projectScope]);
    view['changes-open'] = false;
  }

  async function setRoots(change: { showGlobalFolder?: boolean; topFolder?: TopFolder }): Promise<void> {
    try {
      await writeRootPrefs(change);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      console.warn('files widget: the folder setting was not stored', { change, error: detail });
      say(fk('settings_failed', { detail }), 'error');
    }
  }

  let treeEl = $state<HTMLDivElement | null>(null);
  const stop = $derived(rows.some((row) => row.key === view.selection) ? view.selection : (rows.find(focusable)?.key ?? null));

  async function focusRow(key: string | null): Promise<void> {
    if (!key) return;
    view.selection = key;
    await tick();
    treeEl?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`)?.focus();
  }

  function onTreeKey(event: KeyboardEvent): void {
    const row = rows.find((one) => one.key === stop);
    if (!row) return;
    const expandable = row.kind === 'section' || row.kind === 'group' || (row.kind === 'node' && row.node.is_dir);
    const open = expandable && 'open' in row && row.open;
    let handled = true;
    switch (event.key) {
      case 'ArrowDown': void focusRow(stepFocus(rows, stop, 1)); break;
      case 'ArrowUp': void focusRow(stepFocus(rows, stop, -1)); break;
      case 'Home': void focusRow(stepFocus(rows, stop, -Infinity)); break;
      case 'End': void focusRow(stepFocus(rows, stop, Infinity)); break;
      case 'ArrowRight': if (expandable && !open) setOpen(row, true); else void focusRow(stepFocus(rows, stop, 1)); break;
      case 'ArrowLeft': if (expandable && open) setOpen(row, false); else void focusRow(parentOf(rows, row.key)); break;
      case 'Enter': case ' ': activate(row, event.shiftKey); break;
      case '/': filterEl?.focus(); break;
      default: handled = false;
    }
    if (handled) event.preventDefault();
  }

  function onFilterKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && view.filter) {
      view.filter = '';
      event.preventDefault();
      event.stopPropagation();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      void focusRow(stop);
    } else if (event.key === 'Enter') {
      const first = rows.find((one) => one.kind === 'node' && !one.node.is_dir);
      if (first) {
        event.preventDefault();
        activate(first, false);
      }
    }
  }
</script>

{#snippet chip()}
  <button
    type="button"
    class="oc-chip files-chip"
    data-files-chip
    aria-pressed={justChanges}
    aria-label={fk('changed.chip_label')}
    disabled={changeCount === 0 && !justChanges}
    onclick={toggleJustChanges}
  >{changeCount > 0 ? fk('changed.chip', { n: changeCount }) : fk('changed.chip_none')}</button>
{/snippet}

{#snippet controls(place: 'header' | 'body' | 'corner')}
  {#if place !== 'corner'}{@render chip()}{/if}
{/snippet}

{#snippet projectSummary()}
  {#if sessionId}<ProjectGit {git} {narrow} />{/if}
{/snippet}


<WidgetShell {widget} controls={headerDrawn ? controls : undefined}>
  <div class="files" bind:this={rootEl} data-files data-session={sessionId || undefined}>
    <FilesFilter
      bind:value={() => view.filter, (next) => (view.filter = next)}
      bind:input={filterEl}
      maxlength={FILTER_MAX}
      placeholder={fk('filter.placeholder')}
      label={fk('filter.label')}
      onkeydown={onFilterKey}
      after={!headerDrawn && !corner && !widget.frame?.suppressed ? chip : undefined}
    />

    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="files-tree"
      role="tree"
      aria-label={fk('tree.label', { name: projectName || GLOBAL_PATH })}
      bind:this={treeEl}
      onkeydown={onTreeKey}
      tabindex="-1"
    >
      {#each rows as row (row.key)}
        <FileRow
          {row}
          focused={row.key === stop}
          tag={tagOf(row)}
          label={labelOf(row, query)}
          sub={narrow && row.kind === 'section' ? '' : subOf(row, projectName)}
          title={titleOf(row)}
          readOnlyMark={fk('tree.read_only')}
          readOnlyLabel={fk('tree.read_only_label')}
          tagLabel={row.kind === 'change' ? t(`git.changes.kind.${row.file.kind}`) : ''}
          summary={row.kind === 'section' && row.root === 'workdir' ? projectSummary : undefined}
          onActivate={activate}
          onFocusRow={(key) => (view.selection = key)}
        />
      {/each}
    </div>

    <p class="files-status" class:files-status--error={status?.tone === 'error'} role="status" aria-live="polite" hidden={!status}>
      {status?.text ?? ''}
    </p>
  </div>
</WidgetShell>

<style>
  @layer components {
    .files {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      margin: 0;
      padding: 0;
      background: var(--oc-ground-panel);
      font-family: var(--font-mono);
      color: var(--oc-text-primary);
    }

    .files-tree {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 0 0 var(--oc-space-1);
      outline: none;
    }

    .files-status {
      flex: 0 0 auto;
      margin: 0;
      padding: var(--oc-space-0-5) var(--oc-space-2);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      box-shadow: inset 0 1px 0 0 var(--oc-line-faint);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .files-status[hidden] {
      display: none;
    }

    .files-status--error {
      color: var(--oc-coral);
    }

    .files-chip {
      flex: 0 0 auto;
      white-space: nowrap;
    }

    :global(.oc-frame-title:not(.oc-frame-title--phone)) .files-chip {
      min-height: 0;
    }

    .files-chip[aria-pressed='true'] {
      color: var(--oc-yellow);
      border-color: var(--oc-yellow);
      --_bd: var(--oc-yellow);
    }

    .files-chip:disabled {
      cursor: default;
      opacity: 0.6;
    }
  }
</style>

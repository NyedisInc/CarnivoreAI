<script lang="ts">
  import { announceFailure, familyOf, resourcePush, stampLabel, t, truncatedTip } from '../sdk';
  import type { PanelReadState, ProjectPanelProps } from '../sdk';
  import { TASK_MANAGER_LIST_FAMILY, followTaskManagerDelta } from '../sdk/task-manager-delta';
  import { fetchBoards, openRound } from './board-api';
  import { BOARDS_TOPIC, closedNewestFirst, type BoardListRow } from './board-model';
  import { SHARED_LIST, closedReviewsMoved, shownTaskIds } from './closed-reviews-delta';

  const POLL_MS = 30000;

  /* the shared one */
  function touchesProject(topic: string, key: string): boolean {
    if (familyOf(topic) !== TASK_MANAGER_LIST_FAMILY) return false;
    const listKey = topic.slice(TASK_MANAGER_LIST_FAMILY.length + 1);
    return listKey === '' || listKey === key || listKey === SHARED_LIST;
  }

  const { projectKey, header, isFolded, age, previewOf }: ProjectPanelProps = $props();

  let boards = $state<BoardListRow[]>([]);
  let loaded = $state(false);
  let failed = $state(false);
  let expanded = $state(false);
  let generation = 0;

  const count = $derived(boards.length);
  const read: PanelReadState = $derived(!loaded ? 'loading' : failed && count === 0 ? 'failed' : 'ready');
  const folded = $derived(isFolded(read === 'ready' && count === 0));
  const shown = $derived(previewOf(count, expanded));
  const stateWord = $derived(t('cplug.reviewboard.state.closed'));

  async function load(key: string): Promise<void> {
    const mine = ++generation;
    try {
      const answer = await fetchBoards({ state: 'closed', project: key });
      if (mine !== generation) return;
      boards = closedNewestFirst((answer.boards ?? []).filter((row) => row.state === 'closed'));
      failed = false;
    } catch (err) {
      if (mine !== generation) return;
      console.warn('reviewboard: closed reviews read failed', { project: key, error: err instanceof Error ? err.message : String(err) });
      failed = true;
    } finally {
      if (mine === generation) loaded = true;
    }
  }

  function open(board: BoardListRow): void {
    openRound({ slug: board.slug }).catch((err: unknown) => {
      console.warn('reviewboard: open closed board failed', { slug: board.slug, error: err instanceof Error ? err.message : String(err) });
      announceFailure(t('cplug.reviewboard.closed.open_failed'));
    });
  }

  $effect(() => {
    const key = projectKey;
    boards = [];
    loaded = false;
    failed = false;
    expanded = false;
    void load(key);
    const push = resourcePush();
    const stopBoards = push.pushOrPoll(() => void load(key), POLL_MS, [BOARDS_TOPIC]);
    const doneSeen = new Set<number>();
    const stopTasks = followTaskManagerDelta({
      touches: (delta) => closedReviewsMoved(delta, key, shownTaskIds(boards), doneSeen),
      fallback: (topic) => touchesProject(topic, key),
      refresh: () => void load(key),
    });
    return () => {
      stopBoards();
      stopTasks();
    };
  });
</script>

{@render header(count, read)}
{#if !folded}
  {#if read === 'failed'}
    <p class="ph-empty" data-closed-failed><span class="ph-gone">{t('cplug.reviewboard.closed.failed')}</span></p>
  {:else if read === 'ready' && count === 0}
    <p class="ph-empty">{t('cplug.reviewboard.closed.empty')}</p>
  {:else}
    {#each boards.slice(0, shown) as board (board.slug)}
      {@const title = board.title ?? board.slug}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div class="rb-closed-row ph-scols" data-closed-board={board.slug} onclick={() => open(board)}>
        
        <span class="rb-closed-lead"><span class="ph-mark" title={stateWord}><span class="ph-led ph-led--closed" aria-hidden="true"></span><span class="oc-visually-hidden">{stateWord}</span></span></span>
        <span class="rb-closed-name">
          <button type="button" class="rb-closed-title" use:truncatedTip={title} onclick={(e) => { e.stopPropagation(); open(board); }}>{title}</button>
        </span>
        <span class="rb-closed-meta">
          <span class="rb-closed-task" title={board.task_title ?? undefined}>{board.task_title ?? t('cplug.reviewboard.closed.no_task')}</span>
          <span><span class="ph-tag" data-revisions={board.revisions}>{t('cplug.reviewboard.closed.revisions', { count: board.revisions })}</span></span>
        </span>
        <span class="rb-closed-when" title={t('cplug.reviewboard.closed.revised_at', { when: stampLabel(board.closed_at ?? null) })}>{age(board.closed_at ?? null)}</span>
        <span class="rb-closed-act">
          <button
            type="button"
            class="oc-btn oc-btn--sm oc-btn--confirm"
            data-open-board={board.slug}
            aria-label={t('cplug.reviewboard.closed.open_label', { title })}
            onclick={(e) => { e.stopPropagation(); open(board); }}
          >{t('cplug.reviewboard.closed.open')}</button>
        </span>
        <span class="rb-closed-pad"></span>
      </div>
    {/each}
    {#if shown < count}
      <button type="button" class="oc-btn rb-closed-more" data-show-all onclick={() => (expanded = true)}>
        {t('projects.page.show_all', { count })}
      </button>
    {/if}
    {#if failed}<p class="ph-empty" data-closed-failed><span class="ph-gone">{t('cplug.reviewboard.closed.failed')}</span></p>{/if}
  {/if}
{/if}

<style>
  @layer components {
    .rb-closed-row {
      min-height: 28px;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
      cursor: pointer;
    }

    .rb-closed-row:hover {
      background: var(--oc-ground-hover);
    }

    .rb-closed-lead {
      display: flex;
      align-items: center;
    }

    .rb-closed-meta {
      display: contents;
    }

    .rb-closed-name {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .rb-closed-title {
      min-width: 0;
      overflow: hidden;
      padding: 0;
      border: 1px solid transparent;
      background: none;
      font: inherit;
      font-weight: 500;
      color: var(--oc-text-primary);
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: pointer;
    }

    .rb-closed-task {
      overflow: hidden;
      font-size: var(--oc-fs-label, 11px);
      color: var(--oc-text-secondary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .rb-closed-when {
      font-size: var(--oc-fs-label, 11px);
      font-variant-numeric: tabular-nums;
      color: var(--oc-text-secondary);
      text-align: right;
      white-space: nowrap;
    }

    .rb-closed-act {
      justify-self: end;
    }

    .rb-closed-more {
      margin: var(--oc-space-1) var(--oc-space-3);
    }

    @container ph (max-width: 767px) {
      .rb-closed-row {
        grid-template-columns: 16px minmax(0, 1fr) auto auto auto;
        grid-template-areas:
          'lead name when act kebab'
          'lead meta meta act kebab';
        column-gap: var(--oc-space-2);
        row-gap: 0;
        min-height: 48px;
        padding-block: 2px;
      }

      .rb-closed-lead { grid-area: lead; }
      .rb-closed-name { grid-area: name; }
      .rb-closed-when { grid-area: when; }
      .rb-closed-act { grid-area: act; grid-row: 1 / 3; align-self: center; }
      .rb-closed-pad { grid-area: kebab; grid-row: 1 / 3; width: 44px; min-width: 44px; }

      .rb-closed-meta {
        display: flex;
        grid-area: meta;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
        font-size: var(--oc-fs-label, 11px);
        color: var(--oc-text-dim);
      }

      .rb-closed-task {
        min-width: 0;
        color: var(--oc-text-dim);
      }
    }
  }
</style>

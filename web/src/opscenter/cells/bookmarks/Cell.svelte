<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const BOOKMARKS_WIDGET = defineWidget({ id: 'core.bookmarks', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { sessionBookmarks, releaseSessionBookmarks } from '../../api/session-bookmarks.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { BookmarkList } from '../../../lib/bookmarks/api';
  import { t } from '../../../lib/i18n/index.svelte';
  import BookmarksBody from './BookmarksBody.svelte';
  import { liveRowIds } from './live-rows';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';

  let props: CellProps = $props();

  const widget = useWidget(BOOKMARKS_WIDGET, () => props);
  const sessionId = $derived(widget.sessionId);
  const rowId = $derived.by(() => {
    const info = (sessions.data ?? []).find((s) => s.session.id === sessionId);
    return typeof info?.session_row_id === 'number' ? info.session_row_id : null;
  });
  const live = $derived(liveRowIds(sessions.data ?? []));

  let res = $state<Resource<BookmarkList> | null>(null);

  $effect(() => {
    const id = rowId;
    if (id === null) { res = null; return; }
    res = sessionBookmarks(id);
    return () => releaseSessionBookmarks(id);
  });

  const data = $derived(res?.data ?? null);
  const view = $derived<'none' | 'loading' | 'unknown' | 'empty' | 'list' | 'not_claude'>(
    !sessionId || rowId === null ? 'none'
      : !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading')
      : data.family !== 'claude' ? 'not_claude'
      : data.bookmarks.length === 0 ? 'empty'
      : 'list',
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = {
    list: 'ready', none: 'none', loading: 'loading', unknown: 'error', empty: 'empty', not_claude: 'none',
  };
  const note = $derived(t(view === 'none' ? 'opscenter.cell.bookmarks.no_session' : view === 'not_claude' ? 'bookmarks.not_claude' : `opscenter.cell.bookmarks.${view}`));
</script>

<WidgetShell {widget} status={STATUS[view]} {note}>
  <div class="oc-bkm-cell" data-bookmarks-cell data-view={view} data-session={sessionId || undefined}>
    {#if data}
      <BookmarksBody groups={[{ key: String(rowId), label: null, marks: data.bookmarks }]} live={(id) => id !== null && live.has(id)} />
    {/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-bkm-cell { height: 100%; min-height: 0; overflow-y: auto; }

  }
</style>

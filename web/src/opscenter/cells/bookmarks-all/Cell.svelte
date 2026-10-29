<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const BOOKMARKS_ALL_WIDGET = defineWidget({ id: 'core.bookmarks-all', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { sessions } from '../../api';
  import { allBookmarks, releaseAllBookmarks } from '../../api/session-bookmarks.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { AllBookmarks } from '../../../lib/bookmarks/api';
  import { t } from '../../../lib/i18n/index.svelte';
  import BookmarksBody from '../bookmarks/BookmarksBody.svelte';
  import { liveRowIds } from '../bookmarks/live-rows';
  import { groupBySession } from './group';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import type { WidgetStatus } from '../../widgets/shell/widget-status';
  import type { CellProps } from '../../lib/cell';

  let props: CellProps = $props();

  const widget = useWidget(BOOKMARKS_ALL_WIDGET, () => props);

  let res = $state<Resource<AllBookmarks> | null>(null);

  $effect(() => {
    res = allBookmarks();
    return () => releaseAllBookmarks();
  });

  const data = $derived(res?.data ?? null);
  const live = $derived(liveRowIds(sessions.data ?? []));
  const view = $derived<'loading' | 'unknown' | 'empty' | 'list'>(
    !data ? (res && res.status !== 'loading' ? 'unknown' : 'loading') : data.bookmarks.length > 0 ? 'list' : 'empty',
  );

  const STATUS: Readonly<Record<typeof view, WidgetStatus>> = { list: 'ready', loading: 'loading', unknown: 'error', empty: 'empty' };
  const note = $derived(t(view === 'empty' ? 'opscenter.cell.bookmarks_all.empty' : `opscenter.cell.bookmarks.${view}`));
</script>

<WidgetShell {widget} status={STATUS[view]} {note}>
  <div class="oc-bkm-cell" data-bookmarks-all-cell data-view={view}>
    {#if data}
      <BookmarksBody groups={groupBySession(data.bookmarks, t('opscenter.cell.bookmarks_all.unnamed'))} live={(id) => id !== null && live.has(id)} />
    {/if}
  </div>
</WidgetShell>

<style>
  @layer components {
    .oc-bkm-cell { height: 100%; min-height: 0; overflow-y: auto; }

  }
</style>

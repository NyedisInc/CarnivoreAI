<!-- the detail pane -->
<script lang="ts">
  import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
  import Button from '../base/Button.svelte';
  import State from '../base/State.svelte';
  import Page from '../../opscenter/ui/Page.svelte';
  import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
  import { t } from '../i18n/index.svelte';
  import './automations.css';
  import './page.css';
  import AdvancedTab from './advanced/AdvancedTab.svelte';
  import ItemDrawer from './drawer/ItemDrawer.svelte';
  import FindBox from './overview/FindBox.svelte';
  import OverviewTab from './overview/OverviewTab.svelte';
  import ReviewTab from './review/ReviewTab.svelte';
  import DetailPane from './pane/DetailPane.svelte';
  import { feed } from './feed-store.svelte';
  import { isUnread } from './logic/feed';
  import { closePane, data, feedShown, follow, openNew, reloadFeed, setTop, takeAddress } from './page-store.svelte';
  import { unread } from './read-state.svelte';
  import { writeFeedRun } from './route';
  import { AUTOMATIONS_TABS } from './tabs';

  let { embedded = false }: { embedded?: boolean } = $props();

  // svelte-ignore state_referenced_locally
  let open = $state(embedded);
  let opener: HTMLElement | null = null;

  const toReview = $derived.by(() => {
    const state = { seenAt: unread.seenAt, read: new Set(unread.read) };
    return (feed.unfiltered ?? feed.runs).filter((run) => isUnread(run, state, data.now)).length;
  });
  const tabDefs = $derived<TabDef[]>(
    AUTOMATIONS_TABS.map((id) => ({
      id,
      label: t(`automations.tab.${id}`),
      badge: id === 'sessions' && feed.status === 'ready' ? t('automations.simple.tab.to_review', { n: toReview }) : null,
    })),
  );
  const paneShown = $derived(data.status === 'ready' && (data.top === 'automations' || (data.top === 'advanced' && data.tab === 'automations')));
  const canAdd = $derived(data.targets !== null);

  $effect(() => (open && !data.fixture ? follow() : undefined));
  $effect(() => {
    if (open && data.status === 'ready' && !data.fixture && feed.status === 'idle') void reloadFeed();
  });

  let wasShown = false;
  $effect(() => {
    const shown = open && feedShown();
    if (shown && !wasShown && data.status === 'ready' && !data.fixture && feed.status === 'ready') void reloadFeed();
    wasShown = shown;
  });

  export function show(): void {
    if (!open) {
      opener = captureOpener();
      open = true;
    }
    takeAddress();
  }

  export function close(): void {
    if (!open) return;
    open = false;
    closePane();
    writeFeedRun(null);
    data.pendingEdit = null;
    data.pendingNew = null;
    data.feedRunId = null;
    data.logOpen = false;
    data.commandsOpen = false;
    restoreOpenerFocus(opener);
    opener = null;
  }

  export function isOpen(): boolean {
    return open;
  }
</script>

{#if open}
  <Page
    title={t('automations.page.title')}
    class="pledger ap-page"
    embedded={embedded}
    data-automations=""
    data-pane-open={data.paneOpen ? '' : undefined}
    data-drawer-open={data.drawer ? '' : undefined}
  >
    {#snippet actions()}
      <div class="ap-acts">
        <Button variant="confirm" data-automation-new disabled={!canAdd} onclick={() => openNew()}>{t('automations.new')}</Button>
      </div>
    {/snippet}
    {#snippet tabs()}
      <div class="ap-tabrow">
        <Tabs tabs={tabDefs} active={data.top} onSelect={(id) => setTop(id, true)} label={t('automations.tabs.label')} idBase="automations" class="ap-toptabs" />
        <FindBox />
      </div>
    {/snippet}
    {#if data.notice}<State inline title={data.notice} data-automations-notice />{/if}

    <div {...panelAttrs('automations', data.top)} class="ap-body" data-selected-automation={data.selectedId ?? undefined}>
      {#if data.top === 'advanced'}
        <AdvancedTab />
      {:else if data.top === 'sessions'}
        <ReviewTab />
      {:else}
        <OverviewTab />
      {/if}
    </div>
    {#if paneShown}<DetailPane />{/if}
    <ItemDrawer />
  </Page>
{/if}

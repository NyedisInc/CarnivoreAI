
<script lang="ts">
    import Tabs, { type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import { kindIcon } from '../catalog/card';
    import { PUBLISH_TABS, type PublishTab } from '../catalog/menu/route';
    import type { Translate } from '../sessions/types';
    import { tabKey } from './keys';
    import { KIND_OF_TAB, type TabStat } from './list-model';
    import type { PageStore } from './page-store.svelte';

    interface Props {
        store: PageStore;
        t: Translate;
        stats: Record<PublishTab, TabStat>;
    }
    const { store, t, stats }: Props = $props();

    const tabs = $derived<TabDef[]>(
        PUBLISH_TABS.map((tab) => ({
            id: tab,
            label: t(tabKey(tab)),
            icon: tab === 'submissions' ? 'upload' : (kindIcon(KIND_OF_TAB[tab]) ?? undefined),
            badge: stats[tab].count,
            dot: stats[tab].waits,
            dotLabel: t('publish.page.tab.waits_title'),
        })),
    );
</script>

<div class="d-tabs" data-pp="KindTabs">
    <Tabs {tabs} active={store.tab} onSelect={(id) => store.setTab(id as PublishTab)} label={t('publish.page.tab.list_aria')} idBase="pp" />
</div>

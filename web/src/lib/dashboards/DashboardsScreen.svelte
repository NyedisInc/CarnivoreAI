<!-- your active dashboard is your home screen -->
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import BoardTransfer from '../../opscenter/layout-editor/BoardTransfer.svelte';
    import { enterLayoutEditor } from '../../opscenter/layout-editor/editor.svelte';
    import { homeBoards, viewBoard } from '../../opscenter/engine/home-sync.svelte';
    import { MAX_BOARDS } from '../../opscenter/engine/home-boards';
    import { openHome } from '../../opscenter/api/host';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { Button } from '../base';
    import DashboardList from './DashboardList.svelte';
    import { addDashboard, dashboardsFull, dashboardsUi, sayDashboards } from './dashboard-actions.svelte';
    import { t } from '../i18n/index.svelte';

    let { embedded = false }: { embedded?: boolean } = $props();

    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');

    const full = $derived(dashboardsFull());
    const fullTitle = $derived(full ? t('dashboards.full', { max: MAX_BOARDS }) : '');

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
    }

    export function close(): void {
        if (!open) return;
        open = false;
        query = '';
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    function editHome(): void {
        close();
        void viewBoard(null);
        openHome();
        setTimeout(() => {
            if (!enterLayoutEditor()) sayDashboards(t('dashboards.edit_unavailable'));
        }, 0);
    }
</script>

{#if open}
    <ManagerFrame
        title={t('dashboards.page_title')}
        label={t(homeBoards.list.length === 1 ? 'dashboards.count_one' : 'dashboards.count', { count: homeBoards.list.length })}
        lede={t('dashboards.lede')}
        items={[]}
        status={{ kind: 'ready' }}
        {query}
        onQuery={(next) => (query = next)}
        searchText={{ label: t('dashboards.search_label'), placeholder: t('dashboards.search_placeholder') }}
        showCount={false}
        onClose={embedded ? undefined : close}
        {embedded}
        {t}
    >
        {#snippet actions()}
            <Button
                variant="confirm"
                data-dashboard-new
                disabled={full || dashboardsUi.busy}
                title={fullTitle}
                onclick={() => void addDashboard(false)}><Icon name="plus" size={12} />{t('dashboards.new')}</Button
            >
        {/snippet}
        {#snippet toolbar()}
            <Button
                size="sm"
                data-dashboard-duplicate
                disabled={full || dashboardsUi.busy}
                title={fullTitle}
                onclick={() => void addDashboard(true)}>{t('dashboards.duplicate')}</Button
            >
            <BoardTransfer announce={sayDashboards} />
        {/snippet}
        {#snippet body()}
            <DashboardList {query} onEditHome={editHome} />
        {/snippet}
    </ManagerFrame>
{/if}

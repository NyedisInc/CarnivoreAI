
<script lang="ts">
    import TabStrip, { type TabItem, type TabStripWords } from '../shell/TabStrip.svelte';
    import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
    import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
    import { PAGE_TAB_FAMILY } from '../cells/terminal-group/page-tab-item';
    import { t } from '../../lib/i18n/index.svelte';
    import { layoutByUuid, layouts } from '../../lib/layouts-bridge/api.svelte';
    import { layoutMode } from './mode.svelte';
    import { addable, closeTab, layoutTabs, noteOpen, setTabs, visibleTabs } from './layout-tabs.svelte';

    const HUES = new Set(['cyan', 'violet', 'yellow', 'green', 'coral', 'orange', 'teal', 'rose', 'gold']);
    const GRADIENTS: Record<string, [string, string]> = {
        ember: ['orange', 'yellow'], tide: ['cyan', 'green'], dusk: ['violet', 'coral'], neon: ['cyan', 'violet'],
    };

    let anchor = $state<HTMLElement | null>(null);

    $effect(() => noteOpen(layoutMode.uuid));

    const known = $derived(layouts.data ? layouts.data.map((one) => one.layout_uuid) : null);
    const shown = $derived(visibleTabs(layoutTabs.uuids, known, layoutMode.uuid));
    const offered = $derived(addable(layouts.data ?? [], shown));

    const items = $derived<TabItem[]>(shown.map((uuid) => ({ id: uuid, name: nameOf(uuid), family: PAGE_TAB_FAMILY, nameStyle: colourOf(uuid) || undefined })));

    const words = $derived<TabStripWords>({
        list: t('layout.tabs.label'),
        close: () => t('layout.tabs.close'),
        confirm: (name) => t('layout.tabs.close_confirm', { name }),
        add: t('layout.tabs.add'),
    });

    const offers = $derived<MenuNode[]>(offered.length > 0
        ? offered.map((one) => ({ id: one.layout_uuid, label: one.name, run: () => open(one.layout_uuid) }))
        : [{ id: 'none', label: t('layout.tabs.none'), blocked: t('layout.tabs.none') }]);

    function nameOf(uuid: string): string {
        return uuid === layoutMode.uuid ? layoutMode.name : (layoutByUuid(uuid)?.name ?? '');
    }

    function colourOf(uuid: string): string {
        const saved = layoutByUuid(uuid);
        const sweep = saved?.gradient ? GRADIENTS[saved.gradient] : undefined;
        if (sweep) {
            return `background: linear-gradient(90deg, var(--drawer-hue-${sweep[0]}), var(--drawer-hue-${sweep[1]}));`
                + ' -webkit-background-clip: text; background-clip: text; color: transparent;';
        }
        return saved && HUES.has(saved.colour) ? `color: var(--drawer-hue-${saved.colour});` : '';
    }

    function open(uuid: string): void {
        if (uuid === layoutMode.uuid) return;
        const page = (globalThis as { CloudeWeb?: { layoutPage?: { openLayout?: (uuid: string) => unknown } } })
            .CloudeWeb?.layoutPage;
        if (typeof page?.openLayout === 'function') void page.openLayout(uuid);
        else globalThis.location.assign(`/layout/${encodeURIComponent(uuid)}`);
    }

    function close(uuid: string): void {
        const result = closeTab(shown, uuid, layoutMode.uuid);
        setTabs(result.tabs);
        if (result.open) open(result.open);
    }
</script>

<TabStrip
    {items}
    active={layoutMode.uuid}
    onSelect={open}
    onClose={shown.length > 1 ? close : undefined}
    onNew={(button) => (anchor = anchor ? null : button)}
    newOpen={anchor !== null}
    icons={false}
    follow={false}
    {words}
/>
{#if anchor}
    <CascadeMenu root={offers} {anchor} label={t('layout.tabs.menu')} onClose={() => (anchor = null)} />
{/if}

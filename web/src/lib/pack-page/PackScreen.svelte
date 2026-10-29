
<script lang="ts">
    import { tick } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import '../ledger/ledger-chrome.css';
    import '../manager-frame/manager-frame.css';
    import './pack-page.css';
    import Page from '../../opscenter/ui/Page.svelte';
    import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import PackPanels from './PackPanels.svelte';
    import RosterActions from '../pack-roster/RosterActions.svelte';
    import { rosterUi } from '../pack-roster/roster-ui.svelte';
    import { PACK_TABS, packFragment, packTabOf, type PackTab } from './pack-hash';

    const TAB_KEY = 'carnivore.pack.tab';

    function readTab(): PackTab {
        try {
            const stored = globalThis.localStorage?.getItem(TAB_KEY);
            const found = PACK_TABS.find((slug) => slug === stored);
            if (found) return found;
        } catch {
        }
        return PACK_TABS[0];
    }

    let open = $state(false);
    let tab = $state<PackTab>(readTab());
    let titleEl = $state<HTMLHeadingElement | undefined>();
    let opener: HTMLElement | null = null;

    const tabDefs = $derived<TabDef[]>(PACK_TABS.map((slug) => ({ id: slug, label: t(`hosts.tab.${slug}`) })));

    function pick(slug: string): void {
        tab = slug as PackTab;
        try {
            globalThis.localStorage?.setItem(TAB_KEY, tab);
        } catch {
        }
        if (typeof window !== 'undefined') {
            try {
                window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${packFragment(tab)}`);
            } catch {
            }
        }
    }

    export function show(options?: Record<string, unknown>): void {
        const asked = typeof options?.tab === 'string' ? packTabOf(`#pack/${options.tab}`)?.tab : null;
        const fromHash = typeof window === 'undefined' ? null : packTabOf(window.location.hash);
        const wanted = asked ?? fromHash?.tab ?? null;
        if (fromHash?.ssh && asked === null) rosterUi.landSsh = true;
        if (wanted) pick(wanted);
        if (open) return;
        const focused = typeof document !== 'undefined' ? document.activeElement : null;
        opener = focused instanceof HTMLElement ? focused : null;
        open = true;
        void tick().then(() => titleEl?.focus());
    }

    export function close(): void {
        if (!open) return;
        open = false;
        if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus();
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }
</script>

{#if open}
    {#snippet rosterActions()}<RosterActions />{/snippet}
    <Page class="pledger mgr pack-page" title={t('pack.page.title')} onClose={close} bind:titleEl actions={tab === 'computers' ? rosterActions : undefined}>
        {#snippet tabs()}
            <Tabs tabs={tabDefs} active={tab} onSelect={pick} label={t('pack.tabs.label')} idBase="pack" class="pk-tabs" />
        {/snippet}
        <div class="oc-page__body pk-body">
            <PackPanels {tab} panel={panelAttrs('pack', tab)} />
        </div>
    </Page>
{/if}

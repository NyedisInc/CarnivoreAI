
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import '../ledger/ledger-chrome.css';
    import '../manager-frame/manager-frame.css';
    import '../item-settings/settings-form.css';
    import './settings-page.css';
    import Page from '../../opscenter/ui/Page.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import SearchField from '../../opscenter/ui/SearchField.svelte';
    import Card from '../base/Card.svelte';
    import Select from '../base/Select.svelte';
    import State from '../base/State.svelte';
    import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import SettingsScreenSection from './SettingsScreenSection.svelte';
    import SettingsNav from './SettingsNav.svelte';
    import SettingsSearchResults from './SettingsSearchResults.svelte';
    import SettingsFooter from './SettingsFooter.svelte';
    import SettingControl from './SettingControl.svelte';
    import { settingsDoc } from './settings-doc.svelte';
    import { registerPageDirty } from '../menu-page/menu-page-dirty';
    import { dirtySectionsOf, dirtyTabsOf } from './dirty-places';
    import { searchPluginSettings, searchScreenSections, searchSettings, type PluginMatch } from './settings-search';
    import PluginSettingsSection from './plugin-settings/PluginSettingsSection.svelte';
    import { pluginEntries } from './plugin-settings/plugin-entries';
    import { pluginSettingsIndex } from './plugin-settings/plugin-settings-index.svelte';
    import { PLUGIN_OPTION_PREFIX } from './plugin-settings/plugin-select';
    import {
        SETTINGS_SECTIONS,
        groupKey,
        groupOfSlug,
        rowDomId,
        sectionKey,
        settingById,
        settingsInGroup,
        slugOf,
        type SectionId,
    } from './settings-registry';
    import { tabsOf } from './screen-sections';
    import {
        settingsFragment,
        settingsHashWithoutHighlight,
        settingsHighlightOf,
        settingsPluginFragment,
        settingsPluginOf,
        settingsTabOf,
        writeSettingsFragment,
    } from './settings-hash';
    import { highlightControl } from './settings-highlight';
    import { settingsView } from './settings-view.svelte';
    import { openHostsScreen } from '../pack-page/screen-host';
    import { packFragment, packTabOf } from '../pack-page/pack-hash';

    interface Props {
        t?: Translate;
        embedded?: boolean;
    }

    const { t = reactiveT, embedded = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let titleEl = $state<HTMLHeadingElement | undefined>();
    let searchEl = $state<HTMLInputElement | undefined>();
    let query = $state('');
    let flashId = $state<string | null>(null);
    let flashTimer: ReturnType<typeof setTimeout> | null = null;

    const phoneBar = $derived(viewport.narrow && !embedded);
    const matches = $derived(searchSettings(query, t));
    const sectionHits = $derived(searchScreenSections(query, t));
    const plugins = $derived(pluginEntries(pluginSettingsIndex.rows, t));
    const pluginHits = $derived(searchPluginSettings(query, t, plugins));
    let activePlugin = $state<string | null>(null);
    let pluginAnchor = $state<string | null>(null);
    const pluginEntry = $derived(plugins.find((p) => p.id === activePlugin) ?? null);
    const searching = $derived(query.trim() !== '');
    const counts = $derived.by(() => {
        if (!searching) return null;
        const out: Partial<Record<SectionId, number>> = {};
        for (const m of matches) out[m.setting.section] = (out[m.setting.section] ?? 0) + 1;
        for (const id of sectionHits) out[id] = (out[id] ?? 0) + 1;
        return out;
    });
    const pluginCounts = $derived.by(() => {
        if (!searching) return null;
        const out: Record<string, number> = {};
        for (const m of pluginHits) out[m.entry.id] = (out[m.entry.id] ?? 0) + 1;
        return out;
    });
    const active = $derived(settingsView.section);
    const screen = $derived(SETTINGS_SECTIONS.find((s) => s.id === active)?.screen ?? null);
    const slugs = $derived(tabsOf(active));
    const tab = $derived(settingsView.tabOf(active));
    const group = $derived(!screen && tab ? groupOfSlug(active, tab) : null);
    const tabbed = $derived(slugs.length > 1);
    const dirtyIds = $derived(settingsDoc.dirtyIds);
    const dirtySections = $derived(dirtySectionsOf(dirtyIds));
    const tabDefs = $derived.by((): TabDef[] => {
        const dirtyTabs = dirtyTabsOf(dirtyIds, active);
        return slugs.map((slug) => {
            const g = groupOfSlug(active, slug);
            return { id: slug, label: g ? t(groupKey(g, 'label')) : slug, dot: dirtyTabs.has(slug) };
        });
    });

    // svelte-ignore state_referenced_locally
    if (embedded) void settingsDoc.load();

    $effect(() => (open ? pluginSettingsIndex.start() : undefined));

    $effect(() => {
        if (!activePlugin || !pluginSettingsIndex.read || pluginEntry) return;
        activePlugin = null;
        pluginAnchor = null;
        if (!embedded) writeSettingsFragment(settingsFragment(settingsView.section, settingsView.tabOf(settingsView.section)), 'replace');
    });

    onMount(() => registerPageDirty('settings', () => settingsDoc.dirtyIds.length > 0, () => settingsDoc.discard()));

    export function show(): void {
        const hash = typeof window === 'undefined' ? '' : window.location.hash;
        const pack = /^#?settings\//.test(hash) ? packTabOf(hash) : null;
        if (pack) {
            try {
                window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${packFragment(pack.tab)}`);
            } catch {
            }
            openHostsScreen(pack.tab ?? undefined);
            return;
        }
        void settingsDoc.load();
        const wantedPlugin = typeof window === 'undefined' ? null : settingsPluginOf(window.location.hash);
        if (wantedPlugin) {
            query = '';
            activePlugin = wantedPlugin;
            pluginAnchor = null;
        }
        const wanted = typeof window === 'undefined' ? null : settingsTabOf(window.location.hash);
        if (wanted) {
            activePlugin = null;
            settingsView.section = wanted.section;
            if (wanted.tab) settingsView.setTab(wanted.section, wanted.tab);
        }
        const mark = typeof window === 'undefined' ? null : settingsHighlightOf(window.location.hash);
        if (mark) {
            query = '';
            window.history?.replaceState?.(window.history.state, '', settingsHashWithoutHighlight(window.location.hash));
            void tick().then(() => highlightControl(document, mark));
        }
        if (!embedded && typeof window !== 'undefined' && !mark && !wantedPlugin) {
            writeSettingsFragment(settingsFragment(settingsView.section, settingsView.tabOf(settingsView.section)));
        }
        if (open) return;
        const focused = typeof document !== 'undefined' ? document.activeElement : null;
        opener = focused instanceof HTMLElement ? focused : null;
        open = true;
        void tick().then(() => titleEl?.focus());
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        query = '';
        if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus();
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    function pick(id: SectionId): void {
        query = '';
        activePlugin = null;
        pluginAnchor = null;
        settingsView.section = id;
        if (!embedded) writeSettingsFragment(settingsFragment(id, settingsView.tabOf(id)), 'push');
    }

    function pickPlugin(id: string, anchor: string | null = null): void {
        query = '';
        activePlugin = id;
        pluginAnchor = anchor;
        if (!embedded) writeSettingsFragment(settingsPluginFragment(id), 'push');
    }

    function pickTab(slug: string): void {
        settingsView.setTab(active, slug);
        if (!embedded) writeSettingsFragment(settingsFragment(active, slug), 'replace');
    }

    async function jump(id: string): Promise<void> {
        const def = settingById(id);
        if (!def) return;
        query = '';
        activePlugin = null;
        pluginAnchor = null;
        settingsView.section = def.section;
        settingsView.setTab(def.section, slugOf(def.group));
        if (!embedded) writeSettingsFragment(settingsFragment(def.section, settingsView.tabOf(def.section)), 'replace');
        flashId = id;
        if (flashTimer) clearTimeout(flashTimer);
        flashTimer = setTimeout(() => (flashId = null), 1600);
        await tick();
        const row = typeof document !== 'undefined' ? document.getElementById(rowDomId(id)) : null;
        row?.scrollIntoView?.({ block: 'center' });
        const control = row?.querySelector<HTMLElement>('input, select, textarea, button');
        control?.focus({ preventScroll: true });
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || embedded || !searching) return;
        event.preventDefault();
        query = '';
        searchEl?.focus();
    }

    function onSearchKeydown(event: KeyboardEvent): void {
        const first = matches[0];
        const firstPlugin = pluginHits[0];
        if (event.key === 'Enter' && first) {
            event.preventDefault();
            void jump(first.setting.id);
        } else if (event.key === 'Enter' && firstPlugin) {
            event.preventDefault();
            pickPlugin(firstPlugin.entry.id, firstPlugin.anchor);
        }
    }
</script>

{#snippet railSearch()}
    <SearchField
        bind:input={searchEl}
        value={query}
        onInput={(next) => (query = next)}
        ariaLabel={t('settings.search.label')}
        placeholder={t('settings.search.placeholder')}
        onkeydown={onSearchKeydown}
    />
{/snippet}

{#snippet phoneTabs()}
    <div class="st-phonetabs">
        <div class="st-picker oc-focus-host">
            <span class="st-picker__label">{pluginEntry ? pluginEntry.name : t(sectionKey(active, 'label'))}{pluginEntry ? '' : dirtySections.has(active) ? ' *' : ''}</span>
            <Icon name="chevron-down" size={14} />
            <Select
                aria-label={t('settings.nav.label')}
                data-settings-select
                value={pluginEntry ? `${PLUGIN_OPTION_PREFIX}${pluginEntry.id}` : active}
                onchange={(event) => {
                    const value = (event.currentTarget as HTMLSelectElement).value;
                    if (value.startsWith(PLUGIN_OPTION_PREFIX)) pickPlugin(value.slice(PLUGIN_OPTION_PREFIX.length));
                    else pick(value as SectionId);
                }}
            >
                {#snippet children()}
                    {#each SETTINGS_SECTIONS as section (section.id)}
                        <option value={section.id}>{t(sectionKey(section.id, 'label'))}{dirtySections.has(section.id) ? ' *' : ''}</option>
                    {/each}
                    {#if plugins.length > 0}
                        <optgroup label={t('settings.plugins.heading')}>
                            {#each plugins as plugin (plugin.id)}
                                <option value={`${PLUGIN_OPTION_PREFIX}${plugin.id}`}>{plugin.name}</option>
                            {/each}
                        </optgroup>
                    {/if}
                {/snippet}
            </Select>
        </div>
        {#if tabbed && !searching && !pluginEntry}
            <Tabs
                tabs={tabDefs}
                active={tab ?? ''}
                onSelect={pickTab}
                label={t('settings.tabs.label')}
                idBase={`settings-${active}`}
                class="st-tabs"
            />
        {/if}
    </div>
{/snippet}

{#snippet saveFoot()}
    <SettingsFooter {t} />
{/snippet}

{#snippet loadError()}
    {#if settingsDoc.loadError}
        <State kind="error" title={t('settings.page.load_error')} hint={settingsDoc.loadError} actionLabel={t('manager.error.retry')} onAction={() => void settingsDoc.load()} />
    {/if}
{/snippet}

{#if open}
    <Page
        class="pledger mgr settings-page"
        {embedded}
        title={t('settings.page.title')}
        onClose={embedded ? undefined : close}
        closeLabel={t(MANAGER_KEYS.close)}
        onkeydown={onKeydown}
        bind:titleEl
        search={phoneBar ? railSearch : undefined}
        tabs={phoneBar ? phoneTabs : undefined}
    >
        <div class="oc-page__body st-body" class:st-body--phone={phoneBar}>
            {#if !phoneBar}
                <SettingsNav
                    {t}
                    {active}
                    {counts}
                    dirty={dirtySections}
                    onPick={pick}
                    search={railSearch}
                    {plugins}
                    activePlugin={pluginEntry?.id ?? null}
                    {pluginCounts}
                    onPickPlugin={(id) => pickPlugin(id)}
                />
            {/if}
            <div class="st-content">
                {#if searching}
                    <div class="oc-page__scroll">
                        <div class="oc-page__main st-main">
                            {@render loadError()}
                            <SettingsSearchResults
                                {t}
                                {query}
                                {matches}
                                sections={sectionHits}
                                onJump={(id) => void jump(id)}
                                onOpenSection={pick}
                                pluginMatches={pluginHits}
                                onJumpPlugin={(m: PluginMatch) => pickPlugin(m.entry.id, m.anchor)}
                            />
                        </div>
                    </div>
                {:else}
                    {#if tabbed && !phoneBar && !pluginEntry}
                        <Tabs
                            tabs={tabDefs}
                            active={tab ?? ''}
                            onSelect={pickTab}
                            label={t('settings.tabs.label')}
                            idBase={`settings-${active}`}
                            class="st-tabs"
                        />
                    {/if}
                    <section class="st-section" data-section={pluginEntry ? undefined : active} data-plugin-section={pluginEntry?.id} aria-labelledby="settings-section-title">
                        <h2 class="st-section__title oc-visually-hidden" id="settings-section-title">{pluginEntry ? pluginEntry.name : t(sectionKey(active, 'label'))}</h2>
                        {#if pluginEntry}
                            <PluginSettingsSection entry={pluginEntry} {t} anchor={pluginAnchor} onSaved={() => void pluginSettingsIndex.load()} />
                        {:else if screen}
                            <SettingsScreenSection kind={screen} {tab} panel={tabbed ? panelAttrs(`settings-${active}`, tab ?? '') : {}} />
                        {:else if group}
                            {@const all = settingsInGroup(group)}
                            {@const rows = all.filter((r) => !r.lifecycle)}
                            {@const lifecycle = all.filter((r) => r.lifecycle)}
                            <div class="oc-page__scroll st-panel" {...tabbed ? panelAttrs(`settings-${active}`, tab ?? '') : {}}>
                                <div class="oc-page__main st-main">
                                    {@render loadError()}
                                    <div class="st-group" data-group={group}>
                                        <p class="st-tabhint">{t(groupKey(group, 'hint'))}</p>
                                        <Card title={t(groupKey(group, 'label'))} data-st-frame foot={rows.some((r) => r.saves === 'batch') ? saveFoot : undefined}>
                                            <div class="st-rows">
                                                {#each rows as def (def.id)}
                                                    <SettingControl {def} {t} flash={flashId === def.id} solo={tabbed && rows.length === 1} />
                                                {/each}
                                            </div>
                                        </Card>
                                        {#if lifecycle.length > 0}
                                            <Card title={t('settings.lifecycle.label')} data-st-frame data-st-lifecycle>
                                                <div class="st-rows">
                                                    {#each lifecycle as def (def.id)}
                                                        <SettingControl {def} {t} flash={flashId === def.id} />
                                                    {/each}
                                                </div>
                                            </Card>
                                        {/if}
                                    </div>
                                </div>
                            </div>
                        {/if}
                    </section>
                {/if}
            </div>
        </div>
    </Page>
{/if}

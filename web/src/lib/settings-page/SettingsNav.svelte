
<script lang="ts">
    import type { Snippet } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import Select from '../base/Select.svelte';
    import type { Translate } from '../sessions/types';
    import { SETTINGS_SECTIONS, sectionKey, type SectionId } from './settings-registry';
    import type { PluginEntry } from './plugin-settings/plugin-entries';
    import { PLUGIN_OPTION_PREFIX } from './plugin-settings/plugin-select';

    interface Props {
        t: Translate;
        active: SectionId;
        counts: Partial<Record<SectionId, number>> | null;
        dirty: ReadonlySet<SectionId>;
        onPick: (id: SectionId) => void;
        plugins?: readonly PluginEntry[];
        activePlugin?: string | null;
        pluginCounts?: Readonly<Record<string, number>> | null;
        onPickPlugin?: (id: string) => void;
        search: Snippet;
    }

    const { t, active, counts, dirty, onPick, search, plugins = [], activePlugin = null, pluginCounts = null, onPickPlugin }: Props = $props();

    let list = $state<HTMLElement | null>(null);

    $effect(() => {
        const current = list?.querySelector<HTMLElement>(`[data-section="${active}"]`);
        current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    });
</script>

<nav class="st-nav" aria-label={t('settings.nav.label')}>
    <div class="st-nav__top">
        <div class="st-nav__select">
            <Select
                aria-label={t('settings.nav.label')}
                data-settings-select
                value={activePlugin ? `${PLUGIN_OPTION_PREFIX}${activePlugin}` : active}
                onchange={(event) => {
                    const value = (event.currentTarget as HTMLSelectElement).value;
                    if (value.startsWith(PLUGIN_OPTION_PREFIX)) onPickPlugin?.(value.slice(PLUGIN_OPTION_PREFIX.length));
                    else onPick(value as SectionId);
                }}
            >
                {#snippet children()}
                    {#each SETTINGS_SECTIONS as section (section.id)}
                        <option value={section.id}>{t(sectionKey(section.id, 'label'))}{dirty.has(section.id) ? ' *' : ''}</option>
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
        <div class="st-nav__search">{@render search()}</div>
    </div>
    <div class="st-nav__list" bind:this={list}>
        <List label={t('settings.nav.label')}>
            {#snippet children()}
                {#each SETTINGS_SECTIONS as section (section.id)}
                    {@const current = !counts && !activePlugin && section.id === active}
                    {@const count = counts ? (counts[section.id] ?? 0) : null}
                    <ListRow selected={current}>
                        {#snippet children()}
                            <Button
                                variant="row"
                                aria-current={current ? 'page' : undefined}
                                data-section={section.id}
                                data-empty={count === 0 || undefined}
                                onclick={() => onPick(section.id)}
                            >
                                <span class="st-nav__icon"><Icon name={section.icon} size={14} /></span>
                                <span class="st-nav__label">{t(sectionKey(section.id, 'label'))}</span>
                                {#if dirty.has(section.id)}
                                    <span class="oc-ptab__dot st-nav__dot" data-dirty-dot role="img" aria-label={t('settings.status.unsaved')}></span>
                                {/if}
                                {#if count !== null}
                                    <span class="st-nav__count">{count}</span>
                                {/if}
                            </Button>
                        {/snippet}
                    </ListRow>
                {/each}
            {/snippet}
        </List>
    </div>
    {#if plugins.length > 0}
        <h3 class="oc-label st-nav__heading" data-st-plugins-heading>{t('settings.plugins.heading')}</h3>
        <div class="st-nav__list">
            <List label={t('settings.plugins.heading')}>
                {#snippet children()}
                    {#each plugins as plugin (plugin.id)}
                        {@const current = !pluginCounts && activePlugin === plugin.id}
                        {@const count = pluginCounts ? (pluginCounts[plugin.id] ?? 0) : null}
                        <ListRow selected={current}>
                            {#snippet children()}
                                <Button
                                    variant="row"
                                    aria-current={current ? 'page' : undefined}
                                    data-plugin={plugin.id}
                                    data-empty={count === 0 || undefined}
                                    onclick={() => onPickPlugin?.(plugin.id)}
                                >
                                    <span class="st-nav__icon"><Icon name={plugin.icon} size={14} /></span>
                                    <span class="st-nav__label">{plugin.name}</span>
                                    {#if count !== null}
                                        <span class="st-nav__count">{count}</span>
                                    {/if}
                                </Button>
                            {/snippet}
                        </ListRow>
                    {/each}
                {/snippet}
            </List>
        </div>
    {/if}
</nav>

<style>
    .st-nav {
        display: flex;
        flex-direction: column;
        min-width: 0;
        min-height: 0;
        border-right: 1px solid var(--pl-line);
        background: var(--pl-panel);
        overflow-y: auto;
    }

    .st-nav__top {
        padding: var(--oc-space-2);
    }

    .st-nav__select {
        display: none;
    }

    .st-nav__list {
        padding: 0 0 var(--oc-space-2);
    }

    .st-nav__heading {
        margin: var(--oc-space-3) 0 var(--oc-space-1);
        padding: 0 calc(var(--oc-space-2) * 2);
    }

    .st-nav__list :global([data-btn='row']) {
        flex: 1 1 auto;
        min-width: 0;
        align-items: center;
        color: var(--oc-text-secondary);
    }

    .st-nav__list :global([data-btn='row'][aria-current='page']) {
        color: var(--oc-text-primary);
    }

    .st-nav__list :global([data-btn='row'][aria-current='page'] .st-nav__icon) {
        color: var(--oc-orange);
    }

    .st-nav__list :global([data-btn='row'][data-empty]) {
        color: var(--oc-text-dim);
    }

    .st-nav__icon {
        display: inline-flex;
        flex: 0 0 auto;
        color: var(--oc-text-muted);
    }

    .st-nav__label {
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .st-nav__list :global([data-btn='row']) {
        position: relative;
    }

    .st-nav__dot {
        position: absolute;
        top: 4px;
        left: 11px;
    }

    .st-nav__count {
        flex: 0 0 auto;
        color: var(--oc-text-dim);
        font-size: var(--oc-fs-micro, 10px);
    }

    @media (max-width: 767px) {
        .st-nav {
            border-right: 0;
            border-bottom: 1px solid var(--pl-line);
            overflow: visible;
        }

        .st-nav__top {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            gap: var(--oc-space-2);
            padding: var(--oc-space-1) var(--pl-gutter);
        }

        .st-nav__select {
            display: block;
            min-width: 0;
        }

        .st-nav__list,
        .st-nav__heading {
            display: none;
        }
    }
</style>

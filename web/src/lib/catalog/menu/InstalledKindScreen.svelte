
<script lang="ts">
    import ModsScreen from '../../mods/ModsScreen.svelte';
    import PluginsScreen from '../../plugins-page/PluginsScreen.svelte';
    import SkillsScreen from '../../skills-page/SkillsScreen.svelte';
    import ThemesScreen from '../../themes-page/ThemesScreen.svelte';
    import Tabs, { panelAttrs, type TabDef } from '../../../opscenter/ui/Tabs.svelte';
    import PackSkillsTab from '../../skills-hub/pack/PackSkillsTab.svelte';
    import { packMachines } from '../../pack-machines/pack-machines-store.svelte';
    import SkillsHighlights from '../../skills-hub/SkillsHighlights.svelte';
    import { fetchCensus } from '../../skills-page/skills-api';
    import type { Census } from '../../skills-page/skills-types';
    import { authFetch } from '../../../opscenter/api/auth.svelte';
    import { t } from '../../i18n/index.svelte';
    import { provideInset } from '../../../opscenter/ui/page-inset';
    import type { MenuKind, MenuNode, SkillsTab } from './route';

    interface Props {
        kind: MenuKind;
        tab?: SkillsTab | undefined;
        focusId?: string | null;
        focusTab?: string | null;
        onNavigate: (node: MenuNode) => void;
        onChanged?: () => void;
    }

    const { kind, tab, focusId = null, focusTab = null, onNavigate, onChanged }: Props = $props();

    provideInset();

    let census = $state<Census | null>(null);

    $effect(() => {
        if (kind !== 'skill') return;
        fetchCensus({ projectPath: null, profile: null }, authFetch).then(
            (read) => (census = read),
            () => (census = null),
        );
    });

    const hasPack = $derived((packMachines.data?.machines ?? []).filter((m) => m.is_self || m.paired).length >= 2);
    const view = $derived<'installed' | SkillsTab>(tab === 'pack' && !hasPack ? 'installed' : (tab ?? 'installed'));
    const tabDefs = $derived<TabDef[]>((['installed', 'stats', 'pack'] as const).filter((id) => id !== 'pack' || hasPack).map((id) => ({ id, label: t(`warez.skills.tab.${id}`) })));

    const pickTab = (id: string): void => onNavigate({ scope: 'installed', page: 'kind', kind: 'skill', ...(id === 'installed' ? {} : { tab: id as SkillsTab }) });

    const pick = (key: string, tab?: string): void => onNavigate({ scope: 'installed', page: 'item', kind, key, ...(tab && tab !== 'overview' ? { tab } : {}) });

    const toList = (): void => onNavigate({ scope: 'installed', page: 'kind', kind });

    const toStore = (): void => onNavigate({ scope: 'store', page: 'kind', kind });
</script>

{#snippet highlights()}
    <SkillsHighlights {census} {t} />
{/snippet}

<div class="wik" data-installed-screen={kind}>
    {#if kind === 'theme'}
        <ThemesScreen embedded storeOnly {focusId} onLibrary={toStore} onSelect={pick} {onChanged} />
    {:else if kind === 'plugin'}
        <PluginsScreen embedded storeOnly {focusId} {focusTab} onSelect={pick} {onChanged} />
    {:else if kind === 'skill'}
        {#if !focusId}
            <div class="wik__tabs"><Tabs tabs={tabDefs} active={view} onSelect={pickTab} label={t('warez.skills.tabs')} idBase="wskills" /></div>
        {/if}
        <div class="wik__panel" {...(focusId ? {} : panelAttrs('wskills', view))}>
            {#if view === 'pack' && !focusId}
                <PackSkillsTab />
            {:else}
                <SkillsScreen embedded storeOnly skillPage tab={view === 'stats' && !focusId ? 'census' : 'skills'} {highlights} {focusId} openCatalogPage={toStore} onSelect={pick} onBack={toList} {onChanged} />
            {/if}
        </div>
    {:else}
        <ModsScreen embedded {focusId} onGetMore={toStore} onSelect={pick} />
    {/if}
</div>

<style>
    .wik {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-width: 0;
        min-height: 0;
    }

    .wik__tabs {
        flex: none;
        padding: 0 var(--oc-page-gutter);
        background: var(--oc-ground-tabstrip);
        box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .wik__panel {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        min-height: 0;
    }

    .wik :global(.oc-page.oc-page--embedded) {
        flex: 1 1 auto;
        min-height: 0;
        border: 0;
        border-radius: 0;
    }
</style>

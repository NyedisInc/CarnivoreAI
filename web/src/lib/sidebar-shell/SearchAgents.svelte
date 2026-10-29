
<script lang="ts">
    import Band from './Band.svelte';
    import SearchAgentRow from './SearchAgentRow.svelte';
    import SearchHead from './SearchHead.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import { bandEvents } from './row-events';
    import { t } from '../i18n/index.svelte';
    import { searchD } from '../drawer/search-d.svelte';
    import type { SearchAgentsPlan } from './search-plan';
    import './search-sections.css';

    let { s }: { s: SearchAgentsPlan } = $props();

    const folded = $derived(searchD.folded.agents);
    $effect(() => {
        searchD.agentNames = folded ? [] : s.rows.map((r) => (r.type === 'layout' ? r.key : (r.attrs['data-name'] ?? r.key)));
        return () => { searchD.agentNames = []; searchD.folded.agents = false; };
    });

    let bandEl = $state<HTMLElement | null>(null);
    $effect(() => {
        void searchD.cursor;
        queueMicrotask(() => bandEl?.querySelector('[data-search-cursor="1"]')?.scrollIntoView?.({ block: 'nearest' }));
    });
</script>

<Band kind="session-sidebar-search sd-scope" bind:body={bandEl} attrs={{ 'data-group': s.key, 'data-count': String(s.count), 'data-search-section': 'agents' }} gestures={bandEvents()}><SearchHead label={t('drawer.search.agents')} count={s.count} {folded} onfold={() => (searchD.folded.agents = !searchD.folded.agents)} />{#if !folded}{#each s.rows as r (r.key)}{#if r.type === 'session' && r.search}<SearchAgentRow p={r} />{:else}<SidebarRow {r} />{/if}{/each}{/if}</Band>

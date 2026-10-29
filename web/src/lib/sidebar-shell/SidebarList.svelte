<!-- CANNOT DETERMINE -->
<script lang="ts">
    import BandSection from './BandSection.svelte';
    import LeaderBand from './LeaderBand.svelte';
    import { t } from '../i18n/index.svelte';
    import Band from './Band.svelte';
    import PackSection from './PackSection.svelte';
    import SearchAgents from './SearchAgents.svelte';
    import SearchConversations from './SearchConversations.svelte';
    import type { ShellView } from './shell.svelte';
    import type { BandPart, CompaniesPlan } from './plan';

    let { view }: { view: ShellView } = $props();

    type Item = { key: string; part: BandPart | null; companies: CompaniesPlan | null; inner: BandPart[] };
    const items = $derived.by((): Item[] => {
        const parts = view.plan ? view.plan.parts : [];
        const out: Item[] = [];
        for (let i = 0; i < parts.length; i += 1) {
            const part = parts[i] as BandPart;
            if (part.type !== 'companies') {
                out.push({ key: part.key, part, companies: null, inner: [] });
                continue;
            }
            let end = i + 1;
            while (parts[end]?.type === 'company') end += 1;
            out.push({ key: part.key, part: null, companies: part, inner: parts.slice(i + 1, end) });
            i = end - 1;
        }
        return out;
    });
</script>

{#snippet band(part: BandPart)}{#if part.type === 'section'}<BandSection s={part} />{:else if part.type === 'leader'}<LeaderBand row={part.row} />{:else if part.type === 'company'}<Band kind="session-sidebar-projects session-sidebar-company" attrs={{ 'data-company': part.key, 'data-company-open': part.open ? '1' : '0' }} heading={part.heading}>{#if part.leader}<LeaderBand row={part.leader} />{/if}{#each part.sections as s (s.key)}<BandSection {s} />{/each}{#each part.children ?? [] as child (child.key)}{@render band(child)}{/each}{#if part.empty}<div class="session-sidebar-company__empty">{t('sidebar.company.empty')}</div>{/if}</Band>{:else if part.type === 'groups'}<Band kind="session-sidebar-groups-block" attrs={{ 'data-section': 'groups', 'data-collapsed': part.open ? '0' : '1' }} heading={part.heading}>{#each part.sections as s (s.key)}<BandSection {s} />{/each}</Band>{:else if part.type === 'pack'}<PackSection p={part} />{:else if part.type === 'search-agents'}<SearchAgents s={part} />{:else if part.type === 'search-conversations'}<SearchConversations s={part} />{/if}{/snippet}

{#if view.plan}{@html view.plan.leadHtml}{#each items as item (item.key)}{#if item.companies}<Band kind="session-sidebar-companies" attrs={{ 'data-section': 'companies', 'data-collapsed': item.companies.open ? '0' : '1' }} heading={item.companies.heading}>{#each item.inner as part (part.key)}{@render band(part)}{/each}</Band>{:else if item.part}{@render band(item.part)}{/if}{/each}{@html view.plan.tailHtml}{/if}

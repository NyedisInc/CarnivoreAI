
<script lang="ts" module>
    import type { FacetOption } from './FacetSelect.svelte';

    export interface ToolbarFacet {
        readonly id: string;
        readonly label: string;
        readonly value: string;
        readonly options: readonly FacetOption[];
    }
</script>

<script lang="ts">
    import type { Snippet } from 'svelte';
    import SearchField from './SearchField.svelte';
    import Toolbar from '../../lib/base/Toolbar.svelte';
    import FacetSelect from './FacetSelect.svelte';
    import ViewToggle from '../../lib/manager-frame/ViewToggle.svelte';
    import type { Translate } from '../../lib/sessions/types';
    import type { PageView } from './page-view';

    interface Props {
        query?: string;
        onQuery?: (next: string) => void;
        searchPlaceholder?: string;
        showSearch?: boolean;
        search?: Snippet;
        extras?: Snippet;
        endLead?: Snippet;
        showView?: boolean;
        facets?: readonly ToolbarFacet[];
        onFacet?: (id: string, value: string) => void;
        sort?: { readonly label: string; readonly value: string; readonly options: readonly FacetOption[] };
        onSort?: (value: string) => void;
        view: PageView;
        onView: (next: PageView) => void;
        t: Translate;
    }

    const {
        query = '',
        onQuery = () => {},
        searchPlaceholder = '',
        showSearch = true,
        search,
        extras,
        endLead,
        showView = true,
        facets = [],
        onFacet,
        sort,
        onSort,
        view,
        onView,
        t,
    }: Props = $props();
</script>

{#snippet searchPart()}
    {#if search}{@render search()}{:else}<SearchField value={query} onInput={onQuery} placeholder={searchPlaceholder} data-search="" />{/if}
{/snippet}
{#snippet facetsPart()}
    {#each facets as facet (facet.id)}
        <FacetSelect id={facet.id} label={facet.label} value={facet.value} options={facet.options} onChange={(next) => onFacet?.(facet.id, next)} />
    {/each}
{/snippet}
{#snippet endPart()}
    {#if endLead}<span class="oc-titlebar__sub">{@render endLead()}</span>{/if}
    {#if sort}<FacetSelect id="sort" label={sort.label} value={sort.value} options={sort.options} onChange={(next) => onSort?.(next)} />{/if}
    {#if showView}<ViewToggle view={view === 'cards' ? 'grid' : 'list'} onView={(next) => onView(next === 'grid' ? 'cards' : 'ledger')} {t} />{/if}
{/snippet}

<Toolbar role="search" search={search || showSearch ? searchPart : undefined} filters={facetsPart} {extras} end={endPart} />


<script lang="ts">
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { GUIDE_SECTIONS, type GuideSection } from '../user-guide/guide-content';
    import { filterSections } from '../user-guide/guide-search';
    import GuideBody from '../user-guide/GuideBody.svelte';
    import { DOCS_HASH_BASE, DOCS_TOP_SECTION } from './docs-sections';

    interface Props {
        t?: Translate;
        query?: string;
    }

    const { t = appT, query = '' }: Props = $props();

    const visible = $derived(filterSections(query, GUIDE_SECTIONS));
    const top = $derived(visible.filter((s) => s.id === DOCS_TOP_SECTION));
    const rest = $derived(visible.filter((s) => s.id !== DOCS_TOP_SECTION));

    function goTo(event: MouseEvent, id: string): void {
        event.preventDefault();
        window.location.hash = `${DOCS_HASH_BASE}/${id}`;
        document.querySelector(`[data-docs-section="${id}"]`)?.scrollIntoView({ block: 'start' });
    }
</script>

{#snippet guideSection(section: GuideSection)}
    <section class="docs-guide__section" id="docs-{section.id}" data-docs-section={section.id}>
        <h2 class="oc-label">{section.title}</h2>
        <GuideBody blocks={section.doc.blocks} {t} />
    </section>
{/snippet}

{#if visible.length === 0}
    <p class="docs-guide__none" data-docs-none>{t('docs.search.none')}</p>
{:else}
    {#each top as section (section.id)}
        {@render guideSection(section)}
    {/each}

    <nav class="docs-guide__toc" aria-label={t('docs.toc.label')} data-docs-toc>
        <h2 class="oc-label">{t('docs.toc.label')}</h2>
        <ol class="docs-guide__toc-list">
            {#each visible as section (section.id)}
                <li>
                    <a href="{DOCS_HASH_BASE}/{section.id}" data-docs-toc-link={section.id} onclick={(e) => goTo(e, section.id)}>
                        {section.title}
                    </a>
                </li>
            {/each}
        </ol>
    </nav>

    {#each rest as section (section.id)}
        {@render guideSection(section)}
    {/each}
{/if}

<style>
    .docs-guide__toc,
    .docs-guide__section {
        padding: 12px 0;
        border-bottom: var(--oc-border, 1px) solid var(--oc-line-rule);
    }

    .docs-guide__toc-list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 4px 16px;
        margin: 8px 0 0;
        padding: 0;
        list-style: none;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.5;
    }

    .docs-guide__toc-list a {
        color: var(--oc-cyan);
    }

    .docs-guide__none {
        margin: 16px 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-body, 12px);
    }
</style>

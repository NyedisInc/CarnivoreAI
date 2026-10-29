
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import { tick } from 'svelte';
    import DocsGuide from './DocsGuide.svelte';
    import { docsSectionOf } from './docs-sections';
    import HelpReleases from '../help/HelpReleases.svelte';
    import Check from '../../opscenter/ui/Check.svelte';
    import { readFuzzyPref, writeFuzzyPref } from '../help/fuzzy-pref';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { keySections } from './key-bindings';

    interface Props {
        view: 'docs' | 'keys' | 'changelog';
        t?: Translate;
        embedded?: boolean;
    }

    const { view, t = appT, embedded = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;

    let query = $state('');
    let searchInput = $state<HTMLInputElement | undefined>();
    let fuzzy = $state(readFuzzyPref());

    function setFuzzy(next: boolean): void {
        fuzzy = next;
        writeFuzzyPref(next);
    }

    export function show(): void {
        if (!open) {
            opener = captureOpener();
            open = true;
        }
        if (view === 'docs') void tick().then(scrollToSection);
    }

    function scrollToSection(): void {
        if (typeof document === 'undefined') return;
        const section = docsSectionOf(window.location.hash);
        if (!section) return;
        document.querySelector(`[data-docs-section="${section}"]`)?.scrollIntoView({ block: 'start' });
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    function onSlash(event: KeyboardEvent): void {
        if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || !searchInput) return;
        const target = event.target instanceof HTMLElement ? event.target : null;
        if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
        event.preventDefault();
        searchInput.focus();
    }

    $effect(() => {
        if ((view !== 'changelog' && view !== 'docs') || !open || typeof window === 'undefined') return;
        window.addEventListener('keydown', onSlash);
        return () => window.removeEventListener('keydown', onSlash);
    });

    const sections = $derived(view === 'keys' ? keySections() : []);
</script>

{#snippet fuzzyToggle()}
    <Check label={t('info.page.changelog.fuzzy')} checked={fuzzy} onToggle={setFuzzy} data-changelog-fuzzy="" />
{/snippet}

{#if open}
    <ManagerFrame
        title={t(`info.page.${view}.title`)}
        label={embedded && view === 'keys' ? undefined : t(`info.page.${view}.label`)}
        items={[]}
        status={{ kind: 'ready' }}
        {query}
        onQuery={(next) => (query = next)}
        searchable={view === 'changelog' || view === 'docs'}
        searchText={{ label: t(`info.page.${view === 'docs' ? 'docs' : 'changelog'}.search.label`), placeholder: t(`info.page.${view === 'docs' ? 'docs' : 'changelog'}.search.placeholder`) }}
        bind:searchInput
        toolbar={view === 'changelog' ? fuzzyToggle : undefined}
        showCount={false}
        onClose={embedded ? undefined : close}
        {embedded}
        {t}
    >
        {#snippet body()}
            {#if view === 'docs'}
                <DocsGuide {t} {query} />
            {:else if view === 'changelog'}
                <HelpReleases {query} {fuzzy} onClearQuery={() => (query = '')} />
            {:else}
                {#each sections as section (section.id)}
                    <section class="info-keys" data-keys-section={section.id}>
                        <h2 class="oc-label">{t(section.titleKey)}</h2>
                        <dl class="info-keys__list">
                            {#each section.rows as row (row.keys + row.labelKey)}
                                <dt class="info-keys__key">{row.keys}</dt>
                                <dd class="info-keys__label">{t(row.labelKey)}</dd>
                            {/each}
                        </dl>
                    </section>
                {/each}
            {/if}
        {/snippet}
    </ManagerFrame>
{/if}

<style>
  @layer components {
    .info-keys {
        padding: 12px 0;
        border-bottom: var(--oc-border, 1px) solid var(--oc-line-rule);
    }

    .info-keys__list {
        display: grid;
        grid-template-columns: max-content 1fr;
        gap: 6px 16px;
        margin: 8px 0 0;
        font-family: var(--font-mono);
        font-size: var(--oc-fs-nav, 13px);
    }

    .info-keys__key {
        color: var(--oc-text-primary);
        white-space: nowrap;
    }

    .info-keys__label {
        margin: 0;
        color: var(--oc-text-secondary);
    }
  }
</style>

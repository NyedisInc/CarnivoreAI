
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
    import KeymapScreen from '../keymap/KeymapScreen.svelte';

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
        if (!open || typeof window === 'undefined') return;
        window.addEventListener('keydown', onSlash);
        return () => window.removeEventListener('keydown', onSlash);
    });

    const searchKind = $derived(view === 'keys' ? 'keys' : view === 'docs' ? 'docs' : 'changelog');
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
        searchable
        searchText={searchKind === 'keys'
            ? { label: t('keymap.find.name.label'), placeholder: t('keymap.find.name.placeholder') }
            : { label: t(`info.page.${searchKind}.search.label`), placeholder: t(`info.page.${searchKind}.search.placeholder`) }}
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
                <KeymapScreen {query} {t} />
            {/if}
        {/snippet}
    </ManagerFrame>
{/if}


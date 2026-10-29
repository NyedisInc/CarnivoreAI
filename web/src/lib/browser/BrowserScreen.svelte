<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { browserById, closeBrowser } from './api.svelte';
    import BrowserView from './BrowserView.svelte';
    import PageFrame from './PageFrame.svelte';
    import type { PageInfo } from './page-frame';
    import { openPages, pageById } from './pages.svelte';
    import FileScreen from '../open-files/FileScreen.svelte';
    import { fileById, openFiles } from '../open-files/api.svelte';

    let { onDismiss, onTitle }: { onDismiss?: () => void; onTitle?: (title: string) => void } = $props();

    let current = $state<string | null>(null);
    let resolved = $state<{ kind: 'browser' } | { kind: 'page'; page: PageInfo } | { kind: 'file' } | null>(null);

    const heldFile = $derived(current ? fileById(current) : null);
    const isFile = $derived(resolved?.kind === 'file' || (resolved === null && heldFile !== null));

    const heldPage = $derived(current ? pageById(current) : null);
    const isPage = $derived(resolved?.kind === 'page' || (resolved === null && heldPage !== null));
    const title = $derived(
        isFile
            ? (heldFile?.title ?? '')
            : resolved?.kind === 'page'
            ? (heldPage?.title ?? resolved.page.title)
            : isPage
              ? (heldPage?.title ?? '')
              : current ? (browserById(current)?.label ?? '') : '',
    );
    const fallbackName = $derived(
        isFile ? t('files.screen.untitled')
            : resolved?.kind === 'browser' ? t('browser.page') : isPage ? t('browser.page.untitled') : t('browser.page.loading'),
    );
    const regionLabel = $derived(
        isFile
            ? t('files.screen', { label: title || fallbackName })
            : isPage
            ? t('browser.screen.page', { label: title || fallbackName })
            : resolved?.kind === 'browser'
              ? t('browser.screen', { label: title || fallbackName })
              : title || fallbackName,
    );

    async function resolve(id: string): Promise<void> {
        if (fileById(id)) {
            resolved = { kind: 'file' };
            return;
        }
        if (openPages.status === 'ok' && openFiles.status === 'ok' && !pageById(id)) {
            resolved = { kind: 'browser' };
            return;
        }
        const reads = await Promise.allSettled([openPages.refresh(true), openFiles.refresh(true)]);
        for (const read of reads) {
            if (read.status === 'rejected') console.warn('browser screen: list refresh failed', read.reason);
        }
        if (current !== id) return;
        if (fileById(id)) {
            resolved = { kind: 'file' };
            return;
        }
        const page = pageById(id);
        resolved = page ? { kind: 'page', page: { ...page } } : { kind: 'browser' };
    }

    export function show(id: string): void {
        current = id;
        resolved = null;
        void resolve(id);
    }

    export function close(): void {
        current = null;
        resolved = null;
    }

    export function showing(): string | null {
        return current;
    }

    let view = $state<{ currentUrl?: () => string } | null>(null);

    export function currentUrl(): string | null {
        if (resolved?.kind !== 'browser') return null;
        return view?.currentUrl?.() || null;
    }

    async function closeShown(): Promise<void> {
        const id = current;
        if (!id) return;
        const app = (window as unknown as { App?: { showConfirmModal?: (...a: unknown[]) => Promise<boolean> } }).App;
        const ok = app?.showConfirmModal
            ? await app.showConfirmModal(t('browser.close.confirm'), title || id, t('browser.close.detail'), t('browser.menu.close'), undefined, 'danger')
            : window.confirm(t('browser.close.confirm'));
        if (!ok || current !== id) return;
        try {
            await closeBrowser(id);
        } catch (err) {
            console.error('browser screen: close failed', err);
            alert(t('browser.close_failed', { detail: (err as Error)?.message || String(err) }));
            return;
        }
        onDismiss?.();
    }

    $effect(() => {
        if (current) onTitle?.(title || fallbackName);
    });

    $effect(() => {
        if (resolved?.kind === 'page' && current && openPages.status === 'ok' && !pageById(current)) onDismiss?.();
    });

    $effect(() => {
        if (resolved?.kind === 'file' && current && openFiles.status === 'ok' && !fileById(current)) onDismiss?.();
    });
</script>

{#if current}
    <div class="bscreen" role="region" aria-label={regionLabel}>
        {#key current}
            <div class="bs-body">
                {#if resolved?.kind === 'file' && heldFile}
                    <FileScreen file={heldFile} />
                {:else if resolved?.kind === 'page'}
                    <PageFrame page={resolved.page} />
                {:else if resolved?.kind === 'browser'}
                    <BrowserView bind:this={view} browserId={current} focusAddress onClose={closeShown} />
                {:else}
                    <p class="bs-note" role="status">{t('browser.page.loading')}</p>
                {/if}
            </div>
        {/key}
    </div>
{/if}

<style>
    .bscreen {
        position: relative;
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        pointer-events: auto;
        background: var(--oc-ground-page);
        color: var(--oc-text-primary);
        font-family: var(--oc-font, var(--font-mono));
    }

    .bs-body {
        flex: 1 1 auto;
        min-height: 0;
    }

    .bs-note {
        margin: 0;
        padding: 12px;
        color: var(--oc-text-dim);
        font-size: 13px;
    }
</style>

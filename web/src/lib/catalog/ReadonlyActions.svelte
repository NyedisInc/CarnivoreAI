
<script lang="ts">
    import Button from '../base/Button.svelte';
    import type { Translate } from '../sessions/types';
    import type { CatalogItem } from './types';

    interface Props {
        item: CatalogItem | null;
        id: string | null;
        t: Translate;
    }

    const { item, id, t }: Props = $props();

    const SITE_URL = 'https://carnivore.ai';

    const repository = $derived.by((): string | null => {
        const raw = (item?.fm as { repository?: unknown } | null | undefined)?.repository;
        return typeof raw === 'string' && /^https:\/\/[^\s]+$/.test(raw) ? raw : null;
    });

    let idEl = $state<HTMLElement | undefined>();
    let copied = $state(false);

    function selectId(): void {
        if (!idEl) return;
        const range = document.createRange();
        range.selectNodeContents(idEl);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
    }

    async function copy(): Promise<void> {
        try {
            await navigator.clipboard.writeText(id ?? '');
            copied = true;
            setTimeout(() => { copied = false; }, 1500);
        } catch {
            selectId();
        }
    }
</script>

<div class="acts acts--online" data-acts="online">
    <div class="acts__row">
        <a class="oc-btn oc-btn--confirm" data-act="get" href={SITE_URL} target="_blank" rel="noopener noreferrer">{t('warez.online.get')}</a>
        {#if repository}
            <a class="oc-btn" data-act="source" href={repository} target="_blank" rel="noopener noreferrer">{t('warez.online.source')}</a>
        {/if}
    </div>
    {#if id}
        <div class="acts__row" data-online-id>
            <span class="acts__label">{t('warez.online.id')}</span>
            <code class="acts__id" bind:this={idEl}>{id}</code>
            <Button size="sm" data-act="copy" onclick={() => void copy()}>{copied ? t('warez.online.copied') : t('warez.online.copy')}</Button>
        </div>
    {/if}
</div>

<style>
    .acts {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
    }

    .acts__row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
    }

    .acts a {
        text-decoration: none;
    }

    .acts__label {
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .acts__id {
        min-width: 0;
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-body);
        overflow-wrap: anywhere;
        user-select: all;
    }
</style>

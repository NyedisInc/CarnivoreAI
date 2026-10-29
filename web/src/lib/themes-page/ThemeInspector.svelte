
<script lang="ts">
    import Button from '../base/Button.svelte';
    import ThemePreview from './ThemePreview.svelte';
    import ItemFeedback from '../catalog/ItemFeedback.svelte';
    import type { PreviewPalette } from './preview-palette';
    import type { ThemeManifest } from '../../opscenter/api';
    import { developerOf } from '../catalog/item-feedback';
    import ItemSummary from '../catalog/ItemSummary.svelte';
    import { browserCatalogHost } from '../catalog/catalog';
    import { createRatingsReader } from '../catalog/ratings-reader.svelte';
    import { t } from '../i18n/index.svelte';
    import type { Snippet } from 'svelte';
    import type { RatingsReader } from '../catalog/ratings-reader.svelte';
    import type { CatalogHost } from '../catalog/catalog';

    interface Props {
        manifest: ThemeManifest | null;
        palette: PreviewPalette | null;
        active: boolean;
        starred?: boolean;
        onapply?: () => void;
        onstar?: () => void;
        onexport?: () => void;
        exportNotice?: { text: string; error: boolean } | null;
        actions?: Snippet;
        sourceText?: string;
        reader?: RatingsReader;
        host?: CatalogHost;
        installed?: boolean;
    }

    let {
        manifest, palette, active, starred = false, onapply, onstar, onexport, exportNotice = null,
        actions: pageActions, sourceText, reader: givenReader, host: givenHost, installed = true,
    }: Props = $props();

    const uiSwatches = $derived(
        palette
            ? [
                  ['page', palette.page], ['panel', palette.panel], ['header', palette.header],
                  ['text', palette.fg], ['accent', palette.accent], ['ok', palette.success],
                  ['warn', palette.warning], ['fail', palette.danger],
              ]
            : [],
    );

    const host = givenHost ?? browserCatalogHost();
    const reader = givenReader ?? createRatingsReader(() => manifest?.feedbackItemId ?? null, host, t);

    const developer = $derived(manifest ? developerOf(manifest) : null);
</script>

{#if manifest && palette}
    <div class="tins" data-inspector={manifest.id}>
        <ThemePreview {palette} size="large" label={t('themes.page.preview_of', { name: manifest.name })} />

        <div class="tins-head">
            <h2 class="tins-name">{manifest.name}</h2>
            {#if active}<span class="tins-live">{t('themes.page.active')}</span>{/if}
        </div>

        <ItemSummary
            itemId={manifest.feedbackItemId ?? null}
            {reader}
            id={manifest.id}
            source={sourceText ?? t(manifest.source === 'builtin' ? 'themes.page.source.builtin' : 'themes.page.source.user')}
            {developer}
            version={manifest.version || null}
        >
            {#snippet actions()}
                {#if onstar}
                <Button data-theme-star aria-pressed={starred} onclick={onstar}>
                    <span class="tins-star-glyph" aria-hidden="true">{starred ? '★' : '☆'}</span>
                    {t(starred ? 'themes.page.action.unfavorite' : 'themes.page.action.favorite')}
                </Button>
                {/if}
            {/snippet}
        </ItemSummary>

        {#if manifest.description}<p class="tins-desc">{manifest.description}</p>{/if}

        {#if palette.hasEffects || palette.ascii || palette.background}
            <div class="tins-badges">
                {#if palette.hasEffects}<span class="tins-badge tins-badge-fx">{t('themes.page.badge.effects')}</span>{/if}
                {#if palette.ascii}<span class="tins-badge">{t('themes.page.badge.ascii')}</span>{/if}
                {#if palette.background}<span class="tins-badge">{t('themes.page.badge.background')}</span>{/if}
            </div>
        {/if}

        <section class="tins-block">
            <h3 class="tins-label">{t('themes.page.palette.ui')}</h3>
            <ul class="tins-ui">
                {#each uiSwatches as [name, colour] (name)}
                    <li><span class="tins-chip" style={`background:${colour}`}></span><span class="tins-chip-name">{t(`themes.page.swatch.${name}`)}</span></li>
                {/each}
            </ul>
        </section>

        <section class="tins-block">
            <h3 class="tins-label">{t('themes.page.palette.ansi')}</h3>
            <ul class="tins-ansi" style={`background:${palette.termBg}`}>
                {#each palette.ansi as colour, index (index)}
                    <li style={`background:${colour}`} title={String(index)}></li>
                {/each}
            </ul>
        </section>

        {#if pageActions}
            {@render pageActions()}
        {:else}
        <div class="tins-actions">
            <Button variant="confirm" data-theme-apply onclick={onapply} disabled={active}>
                {t(active ? 'themes.page.action.applied' : 'themes.page.action.apply')}
            </Button>
            {#if onexport}
                <Button data-theme-export onclick={onexport}>
                    {t('themes.page.action.export')}
                </Button>
            {/if}
        </div>
        {#if exportNotice}
            <p class="tins-note" class:tins-note-error={exportNotice.error} role={exportNotice.error ? 'alert' : 'status'} data-theme-export-notice
                >{exportNotice.text}</p
            >
        {/if}
        {#if palette.hasEffects && !active}<p class="tins-note">{t('themes.page.action.effects_note')}</p>{/if}
        <p class="tins-note" data-theme-install-note>{t('themes.page.install_note')}</p>
        {/if}

        <ItemFeedback itemId={manifest.feedbackItemId ?? null} showUnrateable {reader} {host} {installed} />
    </div>
{:else}
    <p class="tins-empty">{t('themes.page.inspector.empty')}</p>
{/if}

<style>
    .tins {
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-width: 0;
    }

    .tins-head {
        display: flex;
        align-items: baseline;
        gap: 10px;
        min-width: 0;
    }

    .tins-name {
        margin: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 18px;
        font-weight: 700;
        color: var(--oc-text-bright);
    }

    .tins-live {
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-green);
    }





    .tins-desc {
        margin: 0;
        font-size: var(--oc-fs-body, 13px);
        line-height: 1.5;
        color: var(--oc-text-secondary);
    }




    .tins-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }

    .tins-badge {
        padding: 2px 7px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-secondary);
    }

    .tins-badge-fx {
        border-color: var(--oc-violet);
        color: var(--oc-violet);
    }

    .tins-block {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .tins-label {
        margin: 0;
        font-size: var(--oc-fs-micro, 10px);
        font-weight: 600;
        letter-spacing: var(--oc-tracking-label, 0.08em);
        text-transform: uppercase;
        color: var(--oc-text-dim);
    }

    .tins-ui {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .tins-ui li {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
    }

    .tins-chip {
        flex: 0 0 auto;
        width: 16px;
        height: 16px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
    }

    .tins-chip-name {
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: var(--oc-fs-micro, 10px);
        text-transform: uppercase;
        color: var(--oc-text-secondary);
    }

    .tins-ansi {
        display: grid;
        grid-template-columns: repeat(8, 1fr);
        gap: 3px;
        margin: 0;
        padding: 4px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
        list-style: none;
    }

    .tins-ansi li {
        height: 18px;
        border-radius: 1px;
    }

    .tins-actions {
        display: flex;
        gap: 8px;
    }

    .tins-star-glyph {
        font-size: 20px;
        line-height: 1;
    }

    :global([data-theme-star][aria-pressed='true']) .tins-star-glyph {
        color: var(--oc-yellow);
    }

    .tins-actions :global([data-theme-apply]) {
        flex: 1 1 auto;
    }

    .tins-note-error {
        color: var(--oc-coral);
    }

    .tins-note,
    .tins-empty {
        margin: 0;
        font-size: var(--oc-fs-label, 12px);
        line-height: 1.5;
        color: var(--oc-text-dim);
    }

    @media (max-width: 1023px) {
        .tins-actions :global([data-btn]),
        :global([data-theme-star]) {
            min-height: var(--oc-tap);
        }
    }
</style>

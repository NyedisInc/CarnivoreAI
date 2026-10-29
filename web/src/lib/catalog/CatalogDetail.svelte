<!-- could not be read -->
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import ReviewBlock from './ReviewBlock.svelte';
    import type { AddProject } from './add-projects';
    import CatalogPluginCredit from '../plugins-page/CatalogPluginCredit.svelte';
    import GradeBlock from './GradeBlock.svelte';
    import CompatBadges from './CompatBadges.svelte';
    import CostBadge from './CostBadge.svelte';
    import InstalledWhere from './InstalledWhere.svelte';
    import AutopsyFacts from './AutopsyFacts.svelte';
    import UsageFacts from './UsageFacts.svelte';
    import ItemFeedback from './ItemFeedback.svelte';
    import KindMark from './KindMark.svelte';
    import ThemeInspector from '../themes-page/ThemeInspector.svelte';
    import type { ThemeManifest } from '../../opscenter/api';
    import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import { createRatingsReader } from './ratings-reader.svelte';
    import InstallCount from './InstallCount.svelte';
    import DetailActions from './DetailActions.svelte';
    import ReadonlyActions from './ReadonlyActions.svelte';
    import { isReadonly } from './readonly';
    import ContentsBlock from './ContentsBlock.svelte';
    import DeprecatedMark from './DeprecatedMark.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import CardMediaImg from './CardMediaImg.svelte';
    import CardImageRow from './CardImageRow.svelte';
    import { previewFor } from './card-image-store.svelte';
    import { latestVersion, type CardView } from './card';
    import { gradeView } from './grade';
    import type { CatalogHost } from './catalog';
    import type { PreviewPalette } from '../themes-page/preview-palette';
    import type { InstallState } from './install-actions';
    import type { CatalogItem, InstalledItem } from './types';

    const MAX_DESCRIPTION_CHARS = 2000;

    const DIGEST_PREFIX_CHARS = 12;

    interface Props {
        card: CardView;
        item: CatalogItem | null;
        installed: readonly InstalledItem[];
        costTotal?: number | null;
        rowState: InstallState;
        host: CatalogHost;
        t: Translate;
        onInstall: () => void;
        onLedgerChange: (id: string, row: InstalledItem | null, installId?: string | null) => void;
        onClose: () => void;
        signedIn?: boolean;
        palette?: PreviewPalette | null;
        onAdd?: ((target: 'global' | 'project', projectPath?: string) => void) | null;
        projects?: readonly AddProject[];
    }

    const {
        card,
        item,
        installed: copies,
        costTotal = null,
        rowState,
        host,
        t,
        onInstall,
        onLedgerChange,
        onClose,
        signedIn = false,
        palette = null,
        onAdd = null,
        projects = [],
    }: Props = $props();
    const readonly = isReadonly();

    let pickedId = $state<string | null>(null);
    const installed = $derived<InstalledItem | null>(
        copies.find((row) => row.install_id && row.install_id === pickedId) ?? copies[0] ?? null,
    );
    const skillName = $derived(
        (copies[0]?.name as string | null | undefined) ?? (card.id ? card.id.split('/').pop() ?? null : null),
    );

    const reader = createRatingsReader(() => card.id ?? null, host, t);

    const thumbGlyph = $derived(Array.from(card.headline || card.id || '?')[0]?.toUpperCase() ?? '?');

    const kindClass = $derived(card.kind && /^[a-z]+$/.test(card.kind) ? card.kind : 'unknown');

    const subLine = $derived(
        [
            kindLabel(card.kind, t) ?? card.kind,
            card.version ? `v${card.version}` : null,
            card.author || card.publisher ? t('skill.card.publisher', { publisher: card.author ?? card.publisher }) : null,
        ]
            .filter(Boolean)
            .join(' \u00b7 '),
    );

    let cardImageOwner = $state(false);
    const preview = $derived(previewFor(card.id));
    const inspectTheme = $derived(card.kind === 'theme' && !!palette);
    const themeManifest = $derived<ThemeManifest>({
        id: card.id ?? '',
        name: card.headline ?? '',
        description: card.brief ?? '',
        author: null,
        publisher: card.publisher ?? null,
        version: card.version ?? null,
        cssVars: {},
        xterm: {},
        source: 'catalog',
        feedbackItemId: card.id ?? null,
    });

    let advancedOpen = $state(false);

    let fetched = $state<CatalogItem | null>(null);
    let loading = $state(false);
    let loadFailure = $state<string | null>(null);

    const entry = $derived(fetched ?? item);

    const version = $derived(latestVersion(entry));

    const gradeLetter = $derived(((): string | null => {
        const g = gradeView(version?.grade ?? null);
        return g.shape === 'graded' && g.letter ? g.letter : null;
    })());

    const ratingsLine = $derived.by(() => {
        const rv = reader.view;
        if (reader.loading && rv.shape === 'unavailable') return t(SKILL_KEYS.ratingLoading);
        if (reader.failure) return t(SKILL_KEYS.ratingUnavailable, { reason: reader.failure });
        if (rv.shape === 'rated') {
            return `${t(SKILL_KEYS.ratingAverage, { average: rv.average ?? 0 })} \u00b7 ${t(SKILL_KEYS.ratingCount, { count: rv.count })}`;
        }
        return t(SKILL_KEYS.ratingNoneShort);
    });

    const commentsLine = $derived.by(() => {
        const rv = reader.view;
        if (reader.failure || rv.shape === 'unavailable') return null;
        const count = rv.texts.filter((row) => row.text).length;
        return count > 0 ? t('warez.detail.comments', { count }) : t('warez.detail.comments_none');
    });

    const description = $derived.by(() => {
        const fm = entry && entry.fm;
        const raw =
            fm && typeof fm === 'object' ? (fm as { description?: unknown }).description : null;
        if (typeof raw !== 'string') return null;
        const trimmed = raw.trim();
        if (!trimmed) return null;
        const points = Array.from(trimmed);
        return points.length <= MAX_DESCRIPTION_CHARS
            ? trimmed
            : points.slice(0, MAX_DESCRIPTION_CHARS - 3).join('') + '...';
    });

    const longDescription = $derived(
        description && card.brief && description !== card.brief && description.length > card.brief.length + 4
            ? description
            : null,
    );

    const digestPrefix = $derived.by(() => {
        const digest = version && version.digest;
        if (typeof digest !== 'string') return null;
        const trimmed = digest.trim();
        return trimmed ? trimmed.slice(0, DIGEST_PREFIX_CHARS) : null;
    });

    $effect(() => {
        const id = card.id;
        fetched = null;
        loadFailure = null;
        if (!id) return;
        let cancelled = false;
        loading = true;
        void (async () => {
            try {
                const answer = await host.item(id);
                if (!cancelled) fetched = answer;
            } catch (error) {
                if (!cancelled) {
                    loadFailure = error instanceof Error ? error.message : String(error ?? '');
                }
            } finally {
                if (!cancelled) loading = false;
            }
        })();
        return () => {
            cancelled = true;
        };
    });
</script>

{#snippet warnings()}
{#if card.deprecated}
    <div class="detail-sec"><DeprecatedMark supersededBy={card.supersededBy} {t} /></div>
{/if}

{#if card.marksInstructionsWrite}
    
    <div class="detail-sec">
        <p class="detail__callout" role="status" data-instructions-write-mark title={t(SKILL_KEYS.cardInstructionsWriteTitle)}>{t(SKILL_KEYS.cardInstructionsWrite)}</p>
    </div>
{/if}

{#if loadFailure}
    
    <p class="detail__callout" role="status">
        {t(SKILL_KEYS.detailUnavailable, { reason: loadFailure })}
    </p>
{/if}
{/snippet}


<section class="detail" aria-label={card.headline || ''}>
    
    <div class="detail__band kind-band kind-band--{kindClass}" aria-hidden="true" data-detail-band></div>

    {#if inspectTheme && palette}
        
        <div class="detail-sec detail__tins" data-detail-sec="inspector">
            <button type="button" class="modal-close detail__close" data-detail-close aria-label={t('warez.detail.close')} onclick={onClose}>&times;</button>
            {@render warnings()}
            <ThemeInspector
                manifest={themeManifest}
                {palette}
                active={false}
                sourceText={card.publisher ?? t('warez.detail.theme_source')}
                {reader}
                {host}
                installed={copies.length > 0 || (card.id ?? '').startsWith('bundled/')}
            >
                {#snippet actions()}{@render acts()}{/snippet}
            </ThemeInspector>
        </div>
    {:else}
    
    <div class="detail__hero" data-detail-hero>
            <div class="oc-card-media detail__art" aria-hidden="true" data-detail-banner>
                {#if card.kind === 'mod'}
                    <Icon name="mod" size={48} />
                {:else}
                    <span class="detail__letter" data-glyph={thumbGlyph}></span>
                {/if}
                {#if card.mediaSha || preview}<CardMediaImg sha={card.mediaSha} previewUrl={preview?.url ?? null} />{/if}
            </div>

        <div class="detail__scrim" aria-hidden="true" data-detail-scrim></div>
        <div class="detail__ovrow">
            <div class="detail__ov detail__ov--tl" data-detail-ov="tl">
                <h2 class="detail__title"><KindMark kind={card.kind} size="lg" {t} /><span class="detail__titletext">{card.headline}</span></h2>
                <div class="detail__sub">{subLine}</div>
                {#if loading}
                    <span class="detail__loading">{t(SKILL_KEYS.detailLoading)}</span>
                {/if}
            </div>
            {#if !readonly}
            <div class="detail__ov detail__ov--tr" data-detail-ov="tr">
                <div class="detail__rate" data-detail-rating>{ratingsLine}</div>
                {#if commentsLine}
                    <div class="detail__sub" data-detail-comments>{commentsLine}</div>
                {/if}
            </div>
            {/if}
        </div>
        <button type="button" class="modal-close detail__close" data-detail-close aria-label={t('warez.detail.close')} onclick={onClose}>&times;</button>
    </div>

    <div class="detail__dt">
        <CatalogPluginCredit credit={card.credit} {t} />
    </div>

    
    <div class="detail-sec" data-detail-sec="brief">
        {#if longDescription ?? card.brief}
            <p class="detail__brief">{longDescription ?? card.brief}</p>
        {/if}
        <CostBadge line item={entry} total={copies.length ? costTotal : null} {t} />
    </div>
    {/if}

    {#if !inspectTheme}{@render warnings()}{/if}

    
    {#snippet acts()}
        {#if card.untrusted}
            <p class="detail__callout" role="status">{t(SKILL_KEYS.cardUntrustedTitle)}</p>
        {/if}
        {#if readonly}
            <ReadonlyActions item={entry} id={card.id ?? null} {t} />
        {:else}
        <DetailActions files={version && typeof version.files === 'number' ? version.files : null} {card} {installed} {rowState} {host} {t} {onInstall} {onLedgerChange} {onAdd} {projects} {copies} />
        {/if}
    {/snippet}
    {#if !inspectTheme}
        <div class="detail-sec detail-sec--acts" data-detail-sec="acts">{@render acts()}</div>
    {/if}

    
    {#if !readonly}
    <div class="detail-sec" data-detail-sec="card-image" hidden={!cardImageOwner}>
        {#key card.id}
            <CardImageRow {card} {host} {signedIn} {t} bind:owns={cardImageOwner} />
        {/key}
    </div>
    {/if}

    
    {#if !inspectTheme && !readonly}
        <div class="detail-sec" data-detail-sec="ratings">
            <div class="detail__sub">{ratingsLine}</div>
        </div>
    {/if}

    
    
    {#if !inspectTheme && !readonly}
        <div class="detail-sec detail-sec--own">
            <ItemFeedback itemId={card.id ?? null} {reader} {host} installed={copies.length > 0 || (card.id ?? '').startsWith('bundled/')} />
        </div>
    {/if}

    {#if copies.length && skillName}
        <div class="detail-sec">
            <UsageFacts skill={skillName} {host} {t} />
            <AutopsyFacts skill={skillName} {host} {t} />
        </div>
    {/if}

    {#if card.tags && card.tags.length}
        <div class="detail-sec">
            <p class="detail__heading">{t(SKILL_KEYS.detailTags)}</p>
            
            <div class="detail__tags">
                {#each card.tags as tag}
                    <span class="detail__tag">{tag}</span>
                {/each}
            </div>
        </div>
    {/if}

    <!-- the theme install sheet -->
    <div class="detail-sec detail__adv">
        <button
            type="button"
            class="detail__advanced"
            data-detail-advanced
            aria-expanded={advancedOpen}
            aria-controls="detail-advanced"
            onclick={() => (advancedOpen = !advancedOpen)}
        >{t(SKILL_KEYS.sheetAdvanced)}</button>
    </div>
    {#if advancedOpen}
        <div id="detail-advanced" data-detail-advanced-body>
    <div class="detail-sec"><CompatBadges item={entry} {t} /></div>
    {#if !readonly}<div class="detail-sec"><InstalledWhere rows={copies} activeId={installed?.install_id ?? null} onPick={(id) => { pickedId = id; }} {t} /></div>{/if}
    <div class="detail-sec"><ReviewBlock review={version ? (version.review ?? null) : null} grade={gradeLetter} part="main" {t} /></div>
            <div class="detail-sec detail-sec--own">
                <GradeBlock grade={version ? (version.grade ?? null) : null} {t} />
                <ReviewBlock review={version ? (version.review ?? null) : null} part="tail" {t} />
            </div>
    {#if !readonly}
    <div class="detail-sec">
        <p class="detail__note">{t(SKILL_KEYS.detailBodyAbsent)}</p>
        <ContentsBlock itemId={card.id ?? null} {host} {t} />
    </div>

    <div class="detail-sec detail__facts" data-detail-provenance>
        <InstallCount itemId={card.id ?? null} {host} {t} />
    </div>
    {/if}
        </div>
    {/if}
</section>

<style>
    .detail {
        display: flex;
        flex-direction: column;
        gap: 0;
        overflow: auto;
        background: var(--cat-panel);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.4;
    }

    .detail__loading {
        color: var(--oc-text-muted);
        font-size: 11px;
    }

    .detail__band {
        height: 3px;
        flex: none;
    }

    .detail__hero {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 160px;
        flex: none;
        overflow: hidden;
        background: var(--oc-surface-2);
    }

    .detail__art {
        --oc-card-media-h: 100%;
        width: 100%;
        height: 100%;
        border: 0;
        border-radius: 0;
        color: var(--oc-text-muted);
    }

    .detail__letter::before {
        content: attr(data-glyph);
    }

    .detail__letter {
        font-size: var(--oc-fs-display, 28px);
        text-transform: uppercase;
        color: var(--oc-text-muted);
    }

    .detail__scrim {
        position: absolute;
        inset: 0 0 auto 0;
        height: 100%;
        pointer-events: none;
        background: linear-gradient(
            to bottom,
            color-mix(in srgb, var(--oc-ground-titlerow) 94%, transparent) 0%,
            color-mix(in srgb, var(--oc-ground-titlerow) 70%, transparent) 55%,
            transparent 100%
        );
    }

    .detail__ovrow {
        position: absolute;
        inset: 0 0 auto 0;
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        padding: 10px 40px 10px 14px;
    }

    .detail__ov {
        display: flex;
        flex-direction: column;
        gap: 3px;
        min-width: 0;
    }

    .detail__ov--tl {
        flex: 1 1 0;
    }

    .detail__ov--tr {
        flex: 0 1 45%;
        align-items: flex-end;
        text-align: right;
    }

    .detail__rate {
        color: var(--oc-text-bright);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .detail__close {
        position: absolute;
        top: 4px;
        right: 4px;
        width: 32px;
        height: 32px;
        font-size: 22px;
        color: var(--oc-text-secondary);
        z-index: 1;
    }

    .detail__close:hover {
        transform: none;
        color: var(--oc-orange);
    }

    .detail__tins {
        position: relative;
        padding-top: 40px;
    }

    .detail__tins > :global(.tins) {
        padding-top: 0;
    }

    .detail__dt {
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-width: 0;
        padding: 12px 16px 0;
    }

    .detail__title {
        min-width: 0;
        margin: 0;
        color: var(--oc-text-bright);
        font-size: var(--oc-fs-figure, 20px);
        font-weight: 400;
        line-height: 1.2;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .detail__titletext {
        min-width: 0;
        overflow-wrap: anywhere;
    }

    .detail__advanced {
        align-self: flex-start;
        padding: 0;
        border: 0;
        background: none;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 11px;
        text-decoration: underline;
        cursor: pointer;
    }

    .detail__sub {
        color: var(--oc-text-muted);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .detail-sec {
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-width: 0;
        padding: 12px 16px;
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .detail-sec:last-child {
        box-shadow: none;
    }

    .detail-sec > :global(section),
    .detail-sec > :global(div:not(.detail__tags)),
    .detail-sec > :global(p) {
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
    }

    .detail-sec > :global(section) {
        gap: 8px;
    }

    .detail-sec :global(.cat-compat__note),
    .detail-sec :global(.cat-where__note) {
        line-height: 1.5;
        color: var(--oc-text-secondary);
    }

    .detail-sec :global(.cat-review__warning) {
        flex-direction: column;
        gap: 2px;
        padding: 6px 0;
    }

    .detail-sec :global([class$='__heading']:not(.detail__heading)),
    .detail-sec :global(.tfb-label),
    .detail__heading {
        margin: 0;
        color: var(--oc-orange);
        font-family: inherit;
        font-size: 10px;
        font-weight: 400;
        letter-spacing: 0.8px;
        text-transform: uppercase;
    }

    .detail__brief {
        margin: 0;
        color: var(--oc-text-secondary);
        line-height: 1.5;
        overflow-wrap: anywhere;
    }


    .detail__facts {
        flex-direction: row;
        flex-wrap: wrap;
        gap: 4px 12px;
    }

    .detail__callout {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.45;
    }

    .detail-sec > .detail__callout {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
    }

    .detail__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 11px;
        line-height: 1.45;
    }

    .detail__tags {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
    }

    .detail__tag {
        padding: 1px 6px;
        border: 1px solid var(--cat-line-quiet);
        border-radius: 3px;
        color: var(--cat-faint);
        font-family: var(--cat-mono);
        font-size: 10px;
    }

    @media (max-width: 767px) {
        .detail-sec :global(button:not([role^='menuitem'])),
        .detail-sec :global(.oc-btn),
        .detail-sec :global(.modal-btn) {
            min-height: 44px;
        }
    }
</style>


<script lang="ts">
    import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { kindIcon, type CardView } from './card';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { InstallState } from './install-actions';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { icons } from '../../opscenter/ui/icons';
    import CardMediaImg from './CardMediaImg.svelte';
    import { previewFor } from './card-image-store.svelte';
    import AddSplit from './AddSplit.svelte';
    import { isReadonly } from './readonly';
    import type { AddProject } from './add-projects';
    import KindMark from './KindMark.svelte';
    import WarezCard from './WarezCard.svelte';
    import './warez-card.css';
        import VerdictMark from './VerdictMark.svelte';
    import ThemePreview from '../themes-page/ThemePreview.svelte';
    import type { InstalledItem } from './types';
    import type { PreviewPalette } from '../themes-page/preview-palette';

    interface Props {
        card: CardView;
        state: InstallState;
        t: Translate;
        onInstall: () => void;
        onUpdate: () => void;
        onOpen?: (() => void) | null;
        rows?: readonly InstalledItem[];
        projects?: readonly AddProject[];
        onAdd?: ((target: 'global' | 'project', projectPath?: string) => void) | null;
        list?: boolean;
        selected?: boolean;
        palette?: PreviewPalette | null;
    }

    const {
        card,
        state,
        t,
        onInstall,
        onUpdate,
        onOpen = null,
        rows = [],
        projects = [],
        onAdd = null,
        list = false,
        selected = false,
        palette = null,
    }: Props = $props();
    const readonly = isReadonly();

    const haveGlobal = $derived(rows.some((row) => row.scope !== 'project'));
    const haveAnyProject = $derived(rows.some((row) => row.scope === 'project'));
    const installedAt = $derived(rows.flatMap((row) => (row.scope === 'project' && row.project_path ? [row.project_path] : [])));

    const kindMod = $derived(card.kind && /^[a-z]+$/.test(card.kind) ? card.kind : 'unknown');
    const isInstalled = $derived(state.kind === 'installed' || state.kind === 'update-available');
    const scoped = $derived(card.kind !== 'theme' && card.kind !== 'mod');

    const iconKnown = $derived(!!card.icon && Object.hasOwn(icons, card.icon));
    const glyph = $derived(Array.from(card.headline || card.id || '?')[0]?.toUpperCase() ?? '?');
    const miniature = $derived(card.kind === 'theme' && palette !== null);
    const preview = $derived(previewFor(card.id));

    const hasFlags = $derived(card.untrusted || (!!card.verdict && card.verdict !== 'clean') || card.deprecated || card.marksInstructionsWrite);

    function rowClick(event: MouseEvent): void {
        if (!onOpen) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest('button, a, select, input, label, [role="menu"]')) return;
        onOpen();
    }
</script>

{#snippet pictureBody(small: boolean)}
    {#if miniature && palette}
        <ThemePreview {palette} size="card" label={card.headline ?? ''} />
    {:else if iconKnown}
        <Icon name={card.icon ?? ''} size={small ? 20 : 32} />
    {:else if card.kind === 'mod'}
        <Icon name="mod" size={small ? 20 : 32} />
    {:else}
        <span class="catalog-card__letter" aria-hidden="true">{glyph}</span>
    {/if}
    {#if card.mediaSha || preview}<CardMediaImg sha={card.mediaSha} previewUrl={preview?.url ?? null} />{/if}
{/snippet}

{#snippet thumb()}{@render pictureBody(false)}{/snippet}

{#snippet picture(small: boolean)}
    <div class="catalog-card__thumb" class:catalog-card__thumb--plain={miniature && !card.mediaSha && !preview} data-card-media>
        {@render pictureBody(small)}
    </div>
{/snippet}

{#snippet flags()}
    {#if card.untrusted}
        <VerdictMark verdict="blocked" {t} label={t('warez.verdict.untrusted')} />
    {:else if card.verdict && card.verdict !== 'clean'}
        <VerdictMark verdict={card.verdict} {t} />
    {/if}
    {#if card.deprecated}<span data-deprecated-mark>{t('skill.deprecated.mark')}</span>{/if}
    {#if card.marksInstructionsWrite}
        <span class="catalog-card__warn" data-instructions-write-mark role="img" aria-label={t(SKILL_KEYS.cardInstructionsWrite)} title={t(SKILL_KEYS.cardInstructionsWriteTitle)}>!</span>
    {/if}
{/snippet}

{#snippet nameBlock()}
    <KindMark kind={card.kind} size="md" {t} />
    {#if card.headline}
        {#if onOpen}
            <button type="button" class="catalog-card__title catalog-card__open" onclick={onOpen}>{card.headline}</button>
        {:else}
            <span class="catalog-card__title">{card.headline}</span>
        {/if}
    {/if}
{/snippet}

{#snippet verdictBlock()}
    {#if card.untrusted}
        <VerdictMark verdict="blocked" {t} label={t('warez.verdict.untrusted')} />
    {:else if card.verdict}
        <VerdictMark verdict={card.verdict} {t} />
    {/if}
{/snippet}

{#snippet act()}
    
    {#if state.kind === 'verifying'}
        <span class="catalog-card__state">{t(SKILL_KEYS.stateVerifying)}</span>
    {:else if state.kind === 'installing'}
        <span class="catalog-card__state">{t(SKILL_KEYS.stateInstalling)}</span>
    {:else if state.kind === 'update-available'}
        <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm catalog-card__btn" data-act="update" onclick={onUpdate}>{t(SKILL_KEYS.actionUpdate)}</button>
    {:else if state.kind === 'installed'}
        <span class="catalog-card__state catalog-card__state--on">{t(SKILL_KEYS.stateInstalled)}</span>
    {:else if state.kind === 'refused'}
        <button type="button" class="oc-btn oc-btn--sm catalog-card__btn" onclick={onInstall}>{t(SKILL_KEYS.actionRetry)}</button>
    {:else if card.untrusted}
        <button type="button" class="oc-btn oc-btn--sm catalog-card__btn" data-act="add" disabled>{t(BROWSE_KEYS.addAction)}</button>
    {:else if onAdd}
        <AddSplit {projects} {installedAt} {haveGlobal} {haveAnyProject} {onAdd} {t} caret={scoped} />
    {:else}
        <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm catalog-card__btn" onclick={onInstall}>{t(SKILL_KEYS.actionInstall)}</button>
    {/if}
{/snippet}

{#if list}
    
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div
        class="catalog-row"
        class:catalog-row--untrusted={card.untrusted}
        data-kind={kindMod}
        data-installed={isInstalled ? 'true' : 'false'}
        aria-current={selected ? 'true' : undefined}
        onclick={rowClick}
    >
        <span class="catalog-row__name">{@render nameBlock()}</span>
        <span class="catalog-row__lead">
            <!-- the picture ladder -->
            {#if miniature}{@render picture(true)}{:else}<Icon name={kindIcon(card.kind) ?? 'grid'} size={16} />{/if}
        </span>
        {#if card.version}<span class="catalog-row__ver">{t('warez.hl.version', { version: card.version })}</span>{:else}<span class="catalog-row__ver"></span>{/if}
        <span class="catalog-row__verdict">{@render verdictBlock()}</span>
        <span class="catalog-row__brief" title={card.brief ?? undefined}>{card.brief ?? ''}</span>
        <span class="catalog-card__slot">{#if !readonly}{@render act()}{/if}</span>
        {#if state.kind === 'refused'}
            <p class="catalog-card__refusal catalog-row__refusal" role="alert">{refusalMessage(state.code, t)}</p>
        {/if}
    </div>
{:else}
    <WarezCard
        kind={card.kind}
        {t}
        name={card.headline ?? null}
        brief={card.brief}
        {onOpen}
        {selected}
        installed={isInstalled}
        untrusted={card.untrusted}
        plain={miniature && !card.mediaSha && !preview}
        {thumb}
        act={readonly ? undefined : act}
        flags={hasFlags ? flags : undefined}
    >
        {#if state.kind === 'refused'}
            <p class="catalog-card__refusal" role="alert">{refusalMessage(state.code, t)}</p>
        {/if}
    </WarezCard>
{/if}

<style>
    .catalog-row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        min-width: 0;
        min-height: 40px;
        padding: 6px 8px;
        box-shadow: inset 0 -1px 0 0 var(--oc-line-faint);
        cursor: pointer;
    }

    .catalog-row:hover {
        background: var(--oc-ground-hover);
    }

    .catalog-row[aria-current='true'] {
        background: var(--oc-orange-tint);
    }

    .catalog-row[data-installed='true'] {
        box-shadow:
            inset 2px 0 0 0 var(--oc-green),
            inset 0 -1px 0 0 var(--oc-line-faint);
    }

    .catalog-row:has(:focus-visible) {
        box-shadow: inset 0 0 0 1px var(--oc-text-muted);
    }

    .catalog-row__lead {
        order: -1;
        display: flex;
        flex: none;
        align-items: center;
        justify-content: center;
        width: 56px;
        color: var(--oc-text-muted);
    }

    .catalog-row__lead .catalog-card__thumb {
        width: 56px;
        border-radius: 2px;
    }

    .catalog-row__lead .catalog-card__letter {
        font-size: 16px;
    }

    .catalog-row__name {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 0 0 188px;
    }

    .catalog-row__ver {
        flex: none;
        width: 56px;
        overflow: hidden;
        color: var(--oc-text-muted);
        font-size: 11px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .catalog-row__verdict {
        display: flex;
        flex: none;
        width: 80px;
        min-width: 0;
    }

    .catalog-row__brief {
        flex: 1 1 0;
        min-width: 0;
        overflow: hidden;
        color: var(--oc-text-secondary);
        font-size: 11px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .catalog-row__refusal {
        flex: 1 1 100%;
        margin: 2px 0 4px;
    }

    /* the reading pane */
    @container (width <= 640px) {
        .catalog-row {
            min-height: 56px;
        }

        .catalog-row__name {
            flex: 1 1 40%;
        }

        .catalog-row__brief {
            display: none;
        }
    }
</style>

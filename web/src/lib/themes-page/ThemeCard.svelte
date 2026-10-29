
<script lang="ts">
    import ThemePreview from './ThemePreview.svelte';
    import WarezCard from '../catalog/WarezCard.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import IconButton from '../base/IconButton.svelte';
    import type { PreviewPalette } from './preview-palette';
    import type { ThemeManifest } from '../../opscenter/api';
    import { t } from '../i18n/index.svelte';

    interface Props {
        manifest: ThemeManifest;
        palette: PreviewPalette;
        selected: boolean;
        active: boolean;
        starred: boolean;
        onselect: () => void;
        onapply: () => void;
        onstar: () => void;
    }

    let { manifest, palette, selected, active, starred, onselect, onapply, onstar }: Props = $props();

    function dbl(event: MouseEvent): void {
        if ((event.target as HTMLElement).closest('button')) return;
        onapply();
    }
</script>

{#snippet thumb()}
    <ThemePreview {palette} label={t('themes.page.preview_of', { name: manifest.name })} />
{/snippet}

{#snippet act()}
    {#if active}<span class="catalog-card__state catalog-card__state--on">{t('themes.page.active')}</span>{/if}
{/snippet}

{#snippet star()}
    <IconButton
        label={t(starred ? 'themes.page.star.remove' : 'themes.page.star.add', { name: manifest.name })}
        variant="quiet"
        pressed={starred}
        data-act="card-star"
        onclick={onstar}
    ><Icon name="star" size={16} strokeWidth={1.4} fill={starred ? 'solid' : 'outline'} /></IconButton>
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<li data-theme-card={manifest.id} ondblclick={dbl}>
    <WarezCard kind="theme" {t} name={manifest.name} brief={manifest.description} onOpen={onselect} {selected} plain {thumb} {act} beside={star} />
</li>

<style>
    li :global([data-act='card-star'][aria-pressed='true']) {
        color: var(--oc-yellow);
    }
</style>

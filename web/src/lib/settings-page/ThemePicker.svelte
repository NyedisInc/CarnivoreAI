
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import { themes, openThemes } from '../../opscenter/api';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { themeFavorites } from '../themes-page/favorites.svelte';
    import { activeGlobalThemeId, applyGlobalTheme, recentThemeIds } from '../themes-page/global-theme';
    import { previewPalette, previewStyle } from '../themes-page/preview-palette';
    import type { ThemeManifest } from '../../opscenter/api';

    interface Props {
        t?: Translate;
    }
    const { t = reactiveT }: Props = $props();

    const QUICK_MAX = 4;

    let active = $state(activeGlobalThemeId());
    let recent = $state(recentThemeIds());

    themeFavorites.start();
    void themes.refresh(true);

    const byId = $derived(
        new Map<string, ThemeManifest>(themes.status === 'ok' && Array.isArray(themes.data) ? themes.data.map((m) => [m.id, m]) : []),
    );
    const current = $derived(byId.get(active) ?? null);
    const quick = $derived(
        [...new Set([...themeFavorites.ids, ...recent])]
            .filter((id) => id !== active && byId.has(id))
            .slice(0, QUICK_MAX)
            .map((id) => byId.get(id)!),
    );

    function choose(id: string): void {
        if (!applyGlobalTheme(id)) return;
        active = id;
        recent = recentThemeIds();
    }
</script>

{#snippet swatch(manifest: ThemeManifest)}
    {@const palette = previewPalette(manifest)}
    <span class="tp__sw" style={previewStyle(palette)} aria-hidden="true">
        <i style="background:var(--p-accent)"></i>
        <i style="background:var(--p-fg);opacity:.7"></i>
        <i style="background:var(--p-success)"></i>
    </span>
{/snippet}

<div class="tp">
    <div class="tp__now">
        <span class="oc-label">{t('settings.theme.current')}</span>
        <Tag>
            <span class="tp__pill">
                {#if current}{@render swatch(current)}{/if}
                <span data-testid="theme-current">{current?.name ?? active}</span>
            </span>
        </Tag>
    </div>

    {#if quick.length}
        <div class="tp__quick" role="group" aria-label={t('settings.theme.quick')}>
            {#each quick as manifest (manifest.id)}
                <Button data-theme-id={manifest.id} onclick={() => choose(manifest.id)}>
                    <span class="tp__chip">
                        {@render swatch(manifest)}
                        <span class="tp__label">{manifest.name}</span>
                    </span>
                </Button>
            {/each}
        </div>
    {/if}

    <Button data-theme-browse onclick={() => openThemes()}>{t('settings.theme.browse')}</Button>
</div>

<style>
  @layer components {
    .tp {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: var(--oc-space-3);
        width: 100%;
    }

    .tp__now,
    .tp__quick {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: flex-end;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .tp__pill {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-2);
    }

    .tp__chip {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-2);
        max-width: 100%;
    }

    .tp__label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .tp__sw {
        display: inline-flex;
        flex-direction: column;
        justify-content: center;
        gap: 2px;
        width: 22px;
        height: 16px;
        padding: 2px;
        border: 1px solid var(--p-border);
        border-radius: 1px;
        background: var(--p-page);
    }

    .tp__sw i {
        display: block;
        height: 2px;
        border-radius: 1px;
    }
  }
</style>

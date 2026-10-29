
<script lang="ts">
    import { onMount } from 'svelte';
    import { themes } from '../../opscenter/api';
    import { t } from '../i18n/index.svelte';
    import { themeFavorites } from './favorites.svelte';
    import { applyGlobalTheme } from './global-theme';
    import { previewPalette } from './preview-palette';
    import { exportTheme } from './theme-export';
    import ThemeInspector from './ThemeInspector.svelte';

    let { themeId }: { themeId: string | null } = $props();

    let exportNotice = $state<{ id: string; text: string; error: boolean } | null>(null);
    let pageTheme = $state<string | null>(null);

    const manifest = $derived((themes.status === 'ok' ? (themes.data ?? []) : []).find((m) => m.id === themeId) ?? null);
    const palette = $derived(manifest ? previewPalette(manifest) : null);

    async function exportSelected(id: string): Promise<void> {
        try {
            const file = await exportTheme(id);
            exportNotice = { id, text: t('themes.page.action.exported', { file }), error: false };
        } catch (err) {
            exportNotice = { id, text: t('themes.page.action.export_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        }
    }

    onMount(() => {
        themeFavorites.start();
        const read = (): void => {
            pageTheme = document.documentElement.dataset.theme ?? null;
        };
        read();
        const observer = new MutationObserver(read);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        return () => observer.disconnect();
    });
</script>

<ThemeInspector
    {manifest}
    {palette}
    active={manifest?.id === pageTheme}
    starred={manifest ? themeFavorites.ids.includes(manifest.id) : false}
    onapply={() => manifest && applyGlobalTheme(manifest.id)}
    onstar={() => manifest && themeFavorites.toggle(manifest.id)}
    onexport={() => manifest && void exportSelected(manifest.id)}
    exportNotice={exportNotice && manifest && exportNotice.id === manifest.id ? exportNotice : null}
/>

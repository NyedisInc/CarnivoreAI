
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { PreviewMode } from '../../widget-preview/protocol';
    import ItemSettingsPanel from '../item-settings/ItemSettingsPanel.svelte';
    import type { ItemSettingsController } from '../item-settings/item-settings-controller.svelte';
    import type { ManagerToggleState } from '../manager-frame/types';
    import { manifestById } from '../../opscenter/widgets/core-manifests';
    import { declaredGlanceHeight } from '../../opscenter/widgets/glance-declarations';
    import { infoKeys } from '../../opscenter/widgets/info/widget-info';
    import { sizeNameKey, type WidgetSizeName } from '../../opscenter/widgets/named-sizes';
    import { viewWidgetId, viewsOf } from '../../opscenter/widgets/views';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import WidgetTile from './WidgetTile.svelte';
    import { factKey, type WidgetItem } from './widgets-adapter';
    import WidgetHero from './WidgetHero.svelte';
    import { PLACES, SIZE_ORDER, boardCell, declaredSizes, fits, orJoin, placeName, type PlaceId } from './places';
    import { boardsHolding, rowsOf } from './places-state.svelte';
    import { heroHeight, previewSizes, realPreviewAvailable } from './preview-sizes';
    import { removeFromPlace } from './places-writes';
    import { showToast } from './undo-toast';

    interface Props {
        item: WidgetItem;
        t: Translate;
        toggle?: ManagerToggleState;
        onToggle: (id: string, next: boolean) => void;
        onMenu: (anchor: HTMLElement, id: string) => void;
        onClose: () => void;
        settingsFor?: (id: string) => ItemSettingsController;
        previews?: boolean;
    }

    const { item, t, toggle, onToggle, onMenu, onClose, settingsFor, previews = true }: Props = $props();

    const PANE_W = 400;

    const manifest = $derived(item.manifest);
    const declared = $derived(declaredSizes(manifest));
    const enabled = $derived(item.enabled !== false);
    const switchable = $derived(item.enabled !== null);

    function firstSize(): WidgetSizeName {
        return (['medium', 'wide', 'tall', 'large'] as const).find((size) => declared.includes(size)) ?? declared[0] ?? 'medium';
    }
    // svelte-ignore state_referenced_locally
    let size = $state<WidgetSizeName>(firstSize());
    let mode = $state<PreviewMode>('sample');
    let viewId = $state<string | null>(null);

    const views = $derived(viewsOf(manifest));
    const drawn = $derived(viewId ? (manifestById(viewWidgetId(manifest, viewId)) ?? manifest) : manifest);
    const realOk = $derived(realPreviewAvailable(drawn));
    const shownMode = $derived<PreviewMode>(realOk ? mode : 'sample');
    const glancePx = $derived(declaredGlanceHeight(manifest.id));
    const heroH = $derived(heroHeight(previewSizes(drawn).find((one) => one.name === size) ?? null, PANE_W));

    const placed = $derived.by(() => {
        const out: { place: PlaceId; label: string; sub: string; key: string | null; board: string | null }[] = [];
        for (const place of ['right', 'bottom', 'drawer', 'glance'] as const) {
            const rows = rowsOf(place);
            rows.forEach((row, index) => {
                if (row.widget === item.id) out.push({ place, label: placeName(place, t), sub: t('widgets.places.pane.position', { n: index + 1, total: rows.length }), key: row.key, board: null });
            });
        }
        for (const one of boardsHolding(boardCell(manifest))) out.push({ place: 'board', label: t('widgets.places.board.named', { name: one.name }), sub: t('widgets.places.pane.on_board'), key: null, board: one.id });
        return out;
    });

    const fitWords = $derived(orJoin(PLACES.filter((def) => fits(manifest, enabled, def.id)).map((def) => t(`widgets.places.${def.id}.short`)), t('widgets.places.or')) || t('widgets.places.pane.fits_none'));

    function remove(row: (typeof placed)[number]): void {
        void removeFromPlace(item.id, item.name, row.place, row.key, row.board, boardCell(manifest), t);
    }

    function flip(): void {
        const next = !enabled;
        if (!next) for (const row of placed) remove(row);
        onToggle(item.id, next);
        showToast({ kind: 'saved', text: t(next ? 'widgets.places.toast.on' : 'widgets.places.toast.off', { widget: item.name }), surface: t('widgets.page.title'), ms: 4000 });
    }
</script>

<section class="pn-detail" data-group={manifest.category} aria-label={item.name} data-widget-pane={item.id}>
    <div class="pn-band" aria-hidden="true"></div>
    <div class="pn-hero" style={`height: ${heroH}px`}>
        <div class="pn-hero__top">
            {#if realOk}
                <div class="oc-seg" role="radiogroup" aria-label={t('widgets.page.preview.data')}>
                    {#each ['sample', 'real'] as const as option (option)}
                        <button type="button" class="oc-seg__item" role="radio" aria-checked={shownMode === option} data-preview-toggle={option} onclick={() => (mode = option)}>{t(option === 'sample' ? 'widgets.places.pane.sample' : 'widgets.places.pane.mine')}</button>
                    {/each}
                </div>
            {:else}
                <span class="pn-note" data-preview-sample-only>{t('widgets.page.preview.sample_only')}</span>
            {/if}
            <button type="button" class="pn-close" aria-label={t('widgets.places.pane.close')} data-k="close" onclick={onClose}><Icon name="close" size={12} /></button>
        </div>
        {#if previews}<WidgetHero manifest={drawn} {size} mode={shownMode} {t} />{/if}
    </div>
    {#if views.length > 0}
        <div class="pn-views">
            <span class="oc-label">{t('widgets.places.pane.view')}</span>
            <div class="oc-seg" role="radiogroup" aria-label={t('widgets.places.pane.view')}>
                {#each views as one, index (one.id)}
                    <button type="button" class="oc-seg__item" role="radio" aria-checked={(viewId ?? views[0]?.id) === one.id} data-view={one.id} onclick={() => (viewId = index === 0 ? null : one.id)}>{t(one.titleKey)}</button>
                {/each}
            </div>
        </div>
    {/if}
    <div class="pn-sizes">
        <div class="oc-seg" role="radiogroup" aria-label={t('widgets.places.pane.size')}>
            {#each SIZE_ORDER as name (name)}
                {@const has = declared.includes(name)}
                <button
                    type="button"
                    class="oc-seg__item"
                    role="radio"
                    data-size={name}
                    aria-checked={name === size}
                    aria-disabled={has ? undefined : 'true'}
                    title={has ? t(sizeNameKey(name)) : t('widgets.places.pane.size_missing', { size: name })}
                    onclick={() => has && (size = name)}
                >{name}</button>
            {/each}
        </div>
    </div>
    {#if size === 'glance'}
        <p class="pn-note">{glancePx !== null ? t('widgets.places.pane.glance_declared', { px: glancePx }) : t('widgets.places.pane.glance_none')}</p>
    {/if}
    <div class="pn-dt">
        <h2 class="pn-title"><WidgetTile id={item.id} icon={manifest.icon} group={manifest.category} /><span>{item.name}</span></h2>
        <div class="pn-sub">{t(factKey('category', manifest.category))} / {fitWords}</div>
        <p class="pn-brief">{t(infoKeys(item.id).about)}</p>
    </div>
    <div class="pn-sec" data-sec="placed">
        <div class="pn-sec__head">
            <span class="oc-label">{t('widgets.places.pane.placed')}</span>
            {#if enabled}<button type="button" class="oc-btn oc-btn--sm" aria-haspopup="menu" data-k="add" onclick={(event) => onMenu(event.currentTarget as HTMLElement, item.id)}>{t('widgets.places.pane.add_to')}</button>{/if}
        </div>
        {#if placed.length === 0}<p class="pn-none">{enabled ? t('widgets.places.pane.none') : t('widgets.places.pane.off_nowhere')}</p>{/if}
        {#each placed as row (`${row.place}:${row.key ?? row.board}`)}
            <div class="pn-place">
                <span class="wp-pmark" data-pl={row.place}>{PLACES.find((def) => def.id === row.place)?.mark}</span>
                <span class="pn-place__name">{row.label}</span>
                <span class="pn-place__sub">{row.sub}</span>
                <button type="button" class="oc-btn oc-btn--sm" aria-label={t('widgets.places.pane.remove_label', { name: item.name, place: row.label })} onclick={() => remove(row)}>{t('widgets.places.pane.remove')}</button>
            </div>
        {/each}
    </div>
    <div class="pn-sec" data-sec="options">
        <div class="pn-sec__head"><span class="oc-label">{t('widgets.places.pane.options')}</span></div>
        {#if manifest.settings}
            <ItemSettingsPanel kind="widget" id={manifest.id} {t} controller={settingsFor?.(manifest.id)} />
        {:else}
            <p class="pn-none">{t('widgets.places.pane.no_options')}</p>
        {/if}
    </div>
    <div class="pn-sec" data-sec="switch">
        <div class="pn-sec__head">
            <span class="oc-label">{t('widgets.places.pane.switch')}</span>
            {#if switchable}
                <button type="button" class="pn-toggle" role="switch" aria-checked={enabled} aria-label={t('widgets.places.pane.switch_label', { name: item.name })} disabled={toggle?.busy} onclick={flip}>{enabled ? t('widgets.places.pane.on') : t('widgets.places.pane.off')}</button>
            {/if}
        </div>
        <p class="pn-switch-note">{!switchable ? t('widgets.places.pane.always_on') : enabled ? t('widgets.places.pane.note_on') : t('widgets.places.pane.note_off')}</p>
        {#if toggle?.error}<p class="pn-switch-note" role="alert">{toggle.error}</p>{/if}
    </div>
</section>

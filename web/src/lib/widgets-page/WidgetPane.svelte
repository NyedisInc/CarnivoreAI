
<script lang="ts">
    import { Button, IconButton, Segmented, Switch, type SegmentedOption } from '../base';
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

    const modeOptions = $derived<SegmentedOption[]>(
        (['sample', 'real'] as const).map((option) => ({ value: option, label: t(option === 'sample' ? 'widgets.places.pane.sample' : 'widgets.places.pane.mine'), attrs: { 'data-preview-toggle': option } })),
    );
    const viewOptions = $derived<SegmentedOption[]>(views.map((one) => ({ value: one.id, label: t(one.titleKey), attrs: { 'data-view': one.id } })));
    const sizeOptions = $derived<SegmentedOption[]>(
        SIZE_ORDER.map((name) => {
            const has = declared.includes(name);
            return { value: name, label: name, disabled: !has, attrs: { 'data-pane-size': name, title: has ? t(sizeNameKey(name)) : t('widgets.places.pane.size_missing', { size: name }) } };
        }),
    );

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
                <Segmented label={t('widgets.page.preview.data')} value={shownMode} options={modeOptions} onchange={(next) => (mode = next === 'real' ? 'real' : 'sample')} />
            {:else}
                <span class="pn-note" data-preview-sample-only>{t('widgets.page.preview.sample_only')}</span>
            {/if}
            <IconButton variant="close" icon="close" label={t('widgets.places.pane.close')} data-k="close" onclick={onClose} />
        </div>
        {#if previews}<WidgetHero manifest={drawn} {size} mode={shownMode} {t} />{/if}
    </div>
    {#if views.length > 0}
        <div class="pn-views">
            <span class="oc-label">{t('widgets.places.pane.view')}</span>
            <Segmented label={t('widgets.places.pane.view')} value={viewId ?? views[0]?.id ?? ''} options={viewOptions} onchange={(next) => (viewId = next === views[0]?.id ? null : next)} />
        </div>
    {/if}
    <div class="pn-sizes">
        <Segmented label={t('widgets.places.pane.size')} value={size} options={sizeOptions} onchange={(next) => (size = next as WidgetSizeName)} />
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
            {#if enabled}<Button size="sm" aria-haspopup="menu" data-k="add" onclick={(event) => onMenu(event.currentTarget as HTMLElement, item.id)}>{t('widgets.places.pane.add_to')}</Button>{/if}
        </div>
        {#if placed.length === 0}<p class="pn-none">{enabled ? t('widgets.places.pane.none') : t('widgets.places.pane.off_nowhere')}</p>{/if}
        {#each placed as row (`${row.place}:${row.key ?? row.board}`)}
            <div class="pn-place">
                <span class="wp-pmark" data-pl={row.place}>{PLACES.find((def) => def.id === row.place)?.mark}</span>
                <span class="pn-place__name">{row.label}</span>
                <span class="pn-place__sub">{row.sub}</span>
                <Button size="sm" variant="danger" aria-label={t('widgets.places.pane.remove_label', { name: item.name, place: row.label })} onclick={() => remove(row)}>{t('widgets.places.pane.remove')}</Button>
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
                <Switch label={enabled ? t('widgets.places.pane.on') : t('widgets.places.pane.off')} bind:checked={() => enabled, () => {}} aria-label={t('widgets.places.pane.switch_label', { name: item.name })} disabled={toggle?.busy} onchange={flip} data-pane-toggle />
            {/if}
        </div>
        <p class="pn-switch-note">{!switchable ? t('widgets.places.pane.always_on') : enabled ? t('widgets.places.pane.note_on') : t('widgets.places.pane.note_off')}</p>
        {#if toggle?.error}<p class="pn-switch-note" role="alert">{toggle.error}</p>{/if}
    </div>
</section>

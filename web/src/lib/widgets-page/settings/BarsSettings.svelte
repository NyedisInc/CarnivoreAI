
<script lang="ts">
    import Button from '../../base/Button.svelte';
    import Card from '../../base/Card.svelte';
    import type { Translate } from '../../sessions/types';
    import { BAR_SIZES, HANDLE_PX } from '../../widget-bars/bar-size';
    import { DEFAULT_BOTTOM_ITEMS, DEFAULT_RAIL_ITEMS, type RailEdge } from '../../session-rail/rail-model';
    import { widgetBars, type BarMode, type BarSize, type BarsTogether } from '../../widget-bars/bar-settings.svelte';
    import { manifestById } from '../../../opscenter/widgets/core-manifests';
    import type { BarPose } from './BarPicture.svelte';
    import BarsEditor from './BarsEditor.svelte';
    import PictureStrip, { type Choice } from './PictureStrip.svelte';
    import TryIt from './TryIt.svelte';
    import { EDGES, SHOW_CHOICES, showChoice, showOps, type ShowChoice } from './settings-model';
    import { applyPick, resetWithUndo, type Pick } from './settings-writes';
    import './settings.css';

    interface Props { t: Translate }
    const { t }: Props = $props();

    const view = $derived(widgetBars.view);
    const SIZES: readonly BarSize[] = ['compact', 'cozy', 'detailed'];
    const MODES: readonly BarMode[] = ['autohide', 'pinned'];
    const TOGETHER: readonly BarsTogether[] = ['both', 'one'];
    const barName = (edge: RailEdge): string => t(edge === 'side' ? 'widgets.places.right.label' : 'widgets.places.bottom.label');

    function titles(items: readonly { widget: string }[]): string {
        return items.map((item) => { const m = manifestById(item.widget); return m ? t(m.titleKey) : item.widget; }).join(', ');
    }
    const hint = $derived(t('widgets.settings.reset_hint', { side: titles(DEFAULT_RAIL_ITEMS), bottom: titles(DEFAULT_BOTTOM_ITEMS) }));

    const poseOf = (edge: RailEdge): BarPose => (view[edge].show ? view[edge].size : 'off');
    const poses = (edge: RailEdge, pose: BarPose): [BarPose, BarPose] => (edge === 'side' ? [pose, poseOf('bottom')] : [poseOf('side'), pose]);

    const apply = (strip: string, pick: Pick): void => void applyPick(strip, pick, t);

    const sizeChoices = (edge: RailEdge): Choice<BarSize>[] => SIZES.map((size) => {
        const px = BAR_SIZES[size][edge].bar;
        const name = t(`widgets.settings.size.${size}`);
        return { value: size, name, note: t('widgets.settings.size.px', { px }), isDefault: size === 'cozy', aria: t('widgets.settings.size.aria', { bar: barName(edge), size: name, px }), pose: poses(edge, size) };
    });
    const showName = (choice: ShowChoice): string => t(`widgets.settings.show.${choice}`);
    const showToastText = (choice: ShowChoice): string => choice === 'both' ? t('widgets.settings.toast.show_both') : choice === 'none' ? t('widgets.settings.toast.show_none') : t('widgets.settings.toast.show_one', { which: showName(choice) });
</script>

<div class="wp-settings">
    <header class="wp-settings__head">
        <div class="wp-settings__intro">
            <span class="wp-settings__title">{t('widgets.settings.title')}</span>
            <span class="wp-settings__lede">{t('widgets.settings.lede')}</span>
        </div>
        <div class="wp-settings__reset">
            <Button variant="danger" size="sm" data-k="settings-reset" disabled={!widgetBars.customized} onclick={() => void resetWithUndo(t)}>{t('widgets.settings.reset')}</Button>
            <span class="wp-settings__hint">{hint}</span>
        </div>
    </header>

    <Card title={t('widgets.settings.size.label')} meta={t('widgets.settings.size.blurb')} data-k="band-size">
        {#each EDGES as edge (edge)}
            <PictureStrip label={t('widgets.settings.size.strip', { bar: barName(edge) })} value={view[edge].size} dim={!view[edge].show} dimNote={t('widgets.settings.hidden')}
                choices={sizeChoices(edge)}
                onSelect={(size) => apply(`size:${edge}`, () => ({ ops: [{ kind: 'bar', edge, patch: { size } }], text: t('widgets.settings.toast.size', { bar: barName(edge), size: t(`widgets.settings.size.${size}`) }) }))} />
        {/each}
    </Card>

    <Card title={t('widgets.settings.show.label')} meta={t('widgets.settings.show.blurb')} data-k="band-show">
        <PictureStrip label={t('widgets.settings.show.strip')} value={showChoice(view)}
            choices={SHOW_CHOICES.map((choice) => ({ value: choice, name: showName(choice), isDefault: choice === 'both', aria: t('widgets.settings.show.aria', { which: showName(choice) }), pose: [choice === 'both' || choice === 'side' ? view.side.size : 'off', choice === 'both' || choice === 'bottom' ? view.bottom.size : 'off'] }))}
            onSelect={(choice) => apply('show', () => ({ ops: showOps(choice, widgetBars.view), text: showToastText(choice) }))} />
    </Card>

    <Card title={t('widgets.settings.mode.label')} meta={t('widgets.settings.mode.blurb')} data-k="band-mode">
        {#each EDGES as edge (edge)}
            <PictureStrip label={t('widgets.settings.mode.strip', { bar: barName(edge) })} value={view[edge].mode}
                choices={MODES.map((mode) => ({ value: mode, name: t(`widgets.settings.mode.${mode}`), isDefault: mode === 'pinned',
                    note: mode === 'autohide' ? t('widgets.settings.mode.autohide_note', { px: HANDLE_PX }) : t('widgets.settings.mode.pinned_note'),
                    aria: t('widgets.settings.mode.aria', { bar: barName(edge), mode: t(`widgets.settings.mode.${mode}`) }), pose: poses(edge, mode === 'autohide' ? 'handle' : view[edge].size) }))}
                onSelect={(mode) => apply(`mode:${edge}`, () => ({ ops: [{ kind: 'bar', edge, patch: { mode } }], text: t('widgets.settings.toast.mode', { bar: barName(edge), mode: t(`widgets.settings.mode.${mode}`) }) }))} />
        {/each}
    </Card>

    <Card title={t('widgets.settings.bars.label')} meta={t('widgets.settings.bars.blurb')} data-k="band-bars">
        <PictureStrip label={t('widgets.settings.bars.strip')} value={view.together}
            choices={TOGETHER.map((choice) => ({ value: choice, name: t(`widgets.settings.bars.${choice}`), isDefault: choice === 'both', aria: t('widgets.settings.bars.aria', { choice: t(`widgets.settings.bars.${choice}`) }), pose: [view.side.size, choice === 'one' ? 'handle' : view.bottom.size] }))}
            onSelect={(choice) => apply('together', () => ({ ops: [{ kind: 'together', value: choice }], text: t('widgets.settings.toast.together', { choice: t(`widgets.settings.bars.${choice}`) }) }))} />
    </Card>

    <Card title={t('widgets.settings.edit.label')} meta={t('widgets.settings.edit.blurb')} data-k="band-edit">
        <BarsEditor {t} />
    </Card>

    <Card title={t('widgets.settings.try.label')} meta={t('widgets.settings.try.blurb')} data-k="band-try">
        <TryIt {t} />
    </Card>
</div>

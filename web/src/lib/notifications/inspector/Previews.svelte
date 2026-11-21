
<script lang="ts">
    import { Segmented } from '../../base';
    import type { Translate } from '../../sessions/types';
    import Preview from './Preview.svelte';
    import type { Sample } from './logic';

    interface Props { name: string; when: string; sample: Sample | null; showAs?: 'app' | 'desk' | 'phone'; on: boolean; ticked: boolean; where: string; corner: boolean; level: string; t: Translate }
    let { name, when, sample, showAs = $bindable('phone'), on, ticked, where, corner, level, t }: Props = $props();

    const off = $derived(!on || !ticked);
    const whatBody = $derived(showAs === 'app' ? t('notify.routing.cap.what.app', { name })
        : showAs === 'desk' ? t('notify.routing.cap.what.desk', { name, corner: t(corner ? 'notify.routing.cap.corner.yes' : 'notify.routing.cap.corner.no') })
        : t('notify.routing.cap.what.phone', { name }));
    const whereText = $derived(!on ? t('notify.routing.cap.where.off', { where: where || t('notify.routing.cap.nowhere') })
        : !ticked ? t('notify.routing.cap.where.not_here', { where: where || t('notify.routing.cap.nowhere') })
        : t('notify.routing.cap.where.here', { where }));
</script>

<div class="ins-prev" data-ins="preview" data-off={on ? undefined : ''}>
    <div class="ins-showas">
        <span class="ins-label">{t('notify.routing.preview.title')}</span>
        <span class="ins-grow-fill"></span>
        <span class="ins-dim">{t('notify.routing.preview.show_as')}</span>
        <Segmented label={t('notify.routing.preview.show_as')} size="sm" bind:value={showAs} data-ins="show-as"
            options={[{ value: 'app', label: t('notify.routing.show.app') }, { value: 'desk', label: t('notify.routing.show.desk') }, { value: 'phone', label: t('notify.routing.show.phone') }]} />
    </div>
    <div class="ins-frame"><Preview kind={showAs} {sample} {off} {corner} {level} {t} /></div>
    <div class="ins-cap" data-ins="caption">
        <div><span class="ins-cap__k">{t('notify.routing.cap.what')}</span>{whatBody}</div>
        <div><span class="ins-cap__k">{t('notify.routing.cap.when')}</span>{when}.</div>
        <div data-ins="cap-where"><span class="ins-cap__k">{t('notify.routing.cap.where')}</span>{whereText}</div>
    </div>
</div>

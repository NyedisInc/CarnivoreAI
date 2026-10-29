
<script lang="ts">
    import Radio from '../base/Radio.svelte';
    import Tag from '../base/Tag.svelte';
    import RadioGroup from '../base/RadioGroup.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import ControlCenterPreview from './appearance/ControlCenterPreview.svelte';
    import FootBarStrip from './appearance/FootBarStrip.svelte';
    import Scaled from './appearance/Scaled.svelte';
    import { FOOT_BAR_LAYOUT_OPTIONS, footBarLayout, type FootBarLayoutOption } from './foot-bar-layout-store.svelte';
    import { footBarItems } from './foot-bar-items-store.svelte';
    import { footBarOrder } from './foot-bar-order-store.svelte';

    interface Props {
        half: 'collapsed' | 'open';
        t?: Translate;
    }
    const { half, t = reactiveT }: Props = $props();

    footBarLayout.start();
    footBarItems.start();
    footBarOrder.start();

    const THUMB_WIDTH = 1000;
    const STRIP_WIDTH = 640;

    const current = $derived(footBarLayout.effective(half));
    const name = (option: string): string => t(`settings.footbarlayout.name.${half}.${option}`);
    const desc = (option: string): string => t(`settings.footbarlayout.desc.${half}.${option}`);
</script>

{#snippet option(opt: FootBarLayoutOption, width: number, strip: boolean)}
    <Radio value={opt} data-option={opt}>
        {#snippet children()}
            <span class="fbl__head"><span class="fbl__name">{name(opt)}</span>{#if current === opt}<Tag tone="ok">{t('settings.choice.in_use')}</Tag>{/if}</span>
            <span class="oc-pick__hint">{desc(opt)}</span>
            <Scaled {width}>{#if strip}<FootBarStrip layout={opt} {t} />{:else}<ControlCenterPreview layout={opt} {t} inert />{/if}</Scaled>
        {/snippet}
    </Radio>
{/snippet}

<div class="fbl" data-half={half}>
    {#if half === 'collapsed'}
        <RadioGroup label={t('settings.footbarlayout.half.collapsed')} bind:value={() => current, (next) => footBarLayout.set(half, next as FootBarLayoutOption)}>
            {#each FOOT_BAR_LAYOUT_OPTIONS as opt (opt)}{@render option(opt, STRIP_WIDTH, true)}{/each}
        </RadioGroup>
    {:else}
        <RadioGroup label={t('settings.footbarlayout.half.open')} orientation="horizontal" bind:value={() => current, (next) => footBarLayout.set(half, next as FootBarLayoutOption)}>
            {#each FOOT_BAR_LAYOUT_OPTIONS as opt (opt)}{@render option(opt, THUMB_WIDTH, false)}{/each}
        </RadioGroup>
        <span class="oc-sub">{t('settings.footbarlayout.preview')}</span>
        <div role="img" aria-label={t('settings.footbarlayout.open_preview.label', { layout: name(current) })}>
            <Scaled width={THUMB_WIDTH} live><ControlCenterPreview layout={current} {t} /></Scaled>
        </div>
    {/if}
</div>

<style>
    .fbl {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        min-width: 0;
        width: 100%;
    }

    .fbl :global([role='radiogroup'] label) {
        flex: 1 1 0;
        min-width: 0;
    }

    .fbl__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-2);
    }

    .fbl__name {
        color: var(--oc-text-primary);
    }

    .fbl :global([role='radiogroup'] label > span) {
        flex: 1 1 auto;
        min-width: 0;
    }

    .fbl[data-half='open'] :global([role='radiogroup']) {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: var(--oc-space-3);
    }

    @media (max-width: 767px) {
        .fbl[data-half='open'] :global([role='radiogroup']) {
            grid-template-columns: minmax(0, 1fr);
        }
    }
</style>


<script lang="ts">
    import { PUBLISH_KEYS } from '../../../../client/js/labels/skill-publish.js';
    import Button from '../base/Button.svelte';
    import Radio from '../base/Radio.svelte';
    import RadioGroup from '../base/RadioGroup.svelte';
    import { kindIcon } from '../catalog/card';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { checkHeroFile, opensAsImage } from './hero-check';
    import { markKind } from './list-model';
    import type { PageProps } from './props';
    import { draftsOf } from './wizard-state.svelte';
    import './wizard.css';

    const { store, t }: PageProps = $props();
    const drafts = $derived(draftsOf(store));

    const location = $derived(store.sel ?? '');
    const hero = $derived(drafts.of(location).hero);
    const kind = $derived(store.folders?.find((f) => f.location === location)?.kind ?? 'skill');
    let picker = $state<HTMLInputElement | null>(null);

    async function take(event: Event): Promise<void> {
        const input = event.currentTarget as HTMLInputElement;
        const file = input.files?.[0];
        input.value = '';
        if (!file || !location) return;
        const checked = await checkHeroFile(file);
        if (!checked.ok) {
            drafts.refuseFile(location, t(checked.key, checked.params));
            return;
        }
        drafts.chooseFile(location, file, { name: file.name, w: checked.w, h: checked.h });
        const url = drafts.of(location).hero.url;
        if (url && !(await opensAsImage(url))) drafts.refuseFile(location, t(PUBLISH_KEYS.cardImageUnreadable));
    }
</script>

<fieldset class="d-hero" data-pp="ImageStep">
    <legend>{t('skill.publish.card_image.label')}</legend>
    <div class="d-hero__opts">
        <RadioGroup label={t('skill.publish.card_image.label')} value={hero.mode} orientation="horizontal" onchange={(v) => drafts.setMode(location, v === 'own' ? 'own' : 'auto')}>
            <Radio value="auto" label={t('publish.page.next.image.make')} />
            <Radio value="own" label={t('publish.page.next.image.own')} />
        </RadioGroup>
    </div>
    <div class="d-hero__row">
        <div>
            {#if hero.mode === 'own'}
                <p class="d-hero__hint">{t('skill.publish.hero.hint')}</p>
                <div class="pp-foot">
                    <Button onclick={() => picker?.click()}>{hero.url ? t('publish.page.next.button.choose_another') : t('skill.publish.card_image.choose')}</Button>
                    {#if hero.url}<Button onclick={() => drafts.discard(location)}>{t('skill.publish.card_image.discard')}</Button>{/if}
                    <input bind:this={picker} class="d-hero__file" type="file" accept="image/png,image/jpeg,image/webp" aria-label={t('skill.publish.card_image.choose_aria')} onchange={(e) => void take(e)} />
                </div>
                {#if hero.url}
                    <p class="d-hero__hint d-hero__meta">{t('skill.publish.card_image.file_meta', { name: hero.name, w: String(hero.w), h: String(hero.h), kb: hero.kb })}<br />{t('skill.publish.card_image.local_only')}</p>
                {/if}
                {#if hero.err}<p class="d-hero__err" role="alert">{hero.err}</p>{/if}
            {:else}
                <p class="d-hero__line">{t('publish.new.hero_default')}</p>
            {/if}
        </div>
        <div class="d-hero__frame">
            <div class="pp-hero-frame">
                {#if hero.mode === 'own' && hero.url}
                    <img alt={t('publish.page.next.image.alt')} src={hero.url} />
                {:else}
                    <div class="d-hero__ph"><span class="pp-glyph" data-kind={markKind(kind)} aria-hidden="true"><Icon name={kindIcon(markKind(kind)) ?? 'grid'} size={22} strokeWidth={1.75} /></span><span>{t('publish.page.next.image.placeholder')}</span></div>
                {/if}
            </div>
        </div>
    </div>
</fieldset>

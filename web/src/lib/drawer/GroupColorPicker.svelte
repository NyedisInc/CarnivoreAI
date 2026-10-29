
<script lang="ts">
    import { t } from '../i18n/index.svelte';
    import { ANIMATIONS, COLORS, GRADIENTS, GRADIENT_STOPS, type RowStyle } from './group-color-palette';

    interface Props {
        style: RowStyle;
        onpick: (field: 'colour' | 'gradient' | 'animation', value: string) => void;
    }
    const { style, onpick }: Props = $props();
</script>

<div class="modal-titlerow group-colour-picker__title">{t('sidebar.group.colour.title')}</div>

<div class="group-colour-picker__region">
    <span class="group-colour-picker__label">{t('sidebar.group.colour.colours')}</span>
    <div class="group-colour-picker__swatches" role="radiogroup" aria-label={t('sidebar.group.colour.colours')}>
        {#each COLORS as c (c)}
            <button type="button" role="radio" data-base-exempt="radio swatch of the popup, drawn by the group-colour-picker classes" class="group-colour-picker__swatch"
                data-style-field="colour" data-style-value={c}
                aria-checked={!style.gradient && style.colour === c ? 'true' : 'false'}
                title={t(`sidebar.group.colour.name.${c}`)} aria-label={t(`sidebar.group.colour.name.${c}`)}
                style={`--swatch: var(--drawer-hue-${c})`}
                onclick={(e) => { e.preventDefault(); e.stopPropagation(); onpick('colour', c); }}></button>
        {/each}
    </div>
</div>

<div class="group-colour-picker__region">
    <span class="group-colour-picker__label">{t('sidebar.group.colour.gradients')}</span>
    <div class="group-colour-picker__swatches" role="radiogroup" aria-label={t('sidebar.group.colour.gradients')}>
        {#each GRADIENTS as g (g)}
            <button type="button" role="radio" data-base-exempt="radio swatch of the popup, drawn by the group-colour-picker classes" class="group-colour-picker__swatch group-colour-picker__swatch--gradient"
                data-style-field="gradient" data-style-value={g}
                aria-checked={style.gradient === g ? 'true' : 'false'}
                title={t(`sidebar.group.colour.gradient.${g}`)} aria-label={t(`sidebar.group.colour.gradient.${g}`)}
                style={`--swatch: var(--drawer-hue-${GRADIENT_STOPS[g][0]}); --swatch-2: var(--drawer-hue-${GRADIENT_STOPS[g][1]})`}
                onclick={(e) => { e.preventDefault(); e.stopPropagation(); onpick('gradient', g); }}></button>
        {/each}
    </div>
</div>

<div class="group-colour-picker__region">
    <span class="group-colour-picker__label">{t('sidebar.group.colour.animation')}</span>
    <div class="group-colour-picker__options" role="radiogroup" aria-label={t('sidebar.group.colour.animation')}>
        {#each ANIMATIONS as a (a)}
            <button type="button" role="radio" data-base-exempt="radio swatch of the popup, drawn by the group-colour-picker classes" class="group-colour-picker__option"
                data-style-field="animation" data-style-value={a}
                aria-checked={(style.animation || 'none') === a ? 'true' : 'false'}
                aria-label={t(`sidebar.group.colour.anim.${a}`)}
                onclick={(e) => { e.preventDefault(); e.stopPropagation(); onpick('animation', a); }}>{t(`sidebar.group.colour.anim.${a}`)}</button>
        {/each}
    </div>
</div>

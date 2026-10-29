
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import {
        DEFAULT_PROJECT_COLOR, SOFT_PROJECT_COLORS, isHexColor, projectColorName, projectColorVar, type ProjectColor,
    } from './palette';
    import ProjectColorPopover from './ProjectColorPopover.svelte';

    interface Props {
        value: string;
        labelledBy: string;
        t: Translate;
        onPick: (key: ProjectColor) => void;
        allowNone?: boolean;
        onPreview?: (hex: string | null) => void;
    }

    const { value, labelledBy, t, onPick, allowNone = false, onPreview }: Props = $props();

    const current = $derived(value.toLowerCase());
    const custom = $derived(isHexColor(value) && projectColorName(value) === null ? current : null);

    function nameOf(color: string): string {
        const name = projectColorName(color);
        return name ? t(`project.color.name.${name}`) : color;
    }

    let open = $state(false);
    let customButton: HTMLButtonElement | null = $state(null);

    const startColor = $derived(isHexColor(value) ? current : DEFAULT_PROJECT_COLOR);

    function commit(hex: string): void {
        open = false;
        onPick(hex.toLowerCase());
    }

    const WHEEL = [0, 60, 120, 180, 240, 300].map((hue) => {
        const pt = (deg: number): string => {
            const r = (((deg - 90) * Math.PI) / 180);
            return `${(10 + 9 * Math.cos(r)).toFixed(2)} ${(10 + 9 * Math.sin(r)).toFixed(2)}`;
        };
        return { fill: `hsl(${hue} 75% 55%)`, d: `M10 10 L${pt(hue)} A9 9 0 0 1 ${pt(hue + 60)} Z` };
    });
</script>

<div class="pc-swatches" role="radiogroup" aria-labelledby={labelledBy} data-project-color-picker>
    {#if allowNone}
        <button
            type="button"
            class="pc-swatch pc-swatch--none"
            role="radio"
            aria-checked={value === ''}
            aria-label={t('project.color.none')}
            data-project-color-none
            onclick={() => onPick('')}
        ></button>
    {/if}
    {#each SOFT_PROJECT_COLORS as swatch (swatch.hex)}
        <button
            type="button"
            class="pc-swatch"
            role="radio"
            aria-checked={current === swatch.hex}
            aria-label={t(`project.color.name.${swatch.name}`)}
            title={t(`project.color.name.${swatch.name}`)}
            data-project-color={swatch.hex}
            style:--_swatch={swatch.hex}
            onclick={() => onPick(swatch.hex)}
        ></button>
    {/each}
    <button
        type="button"
        class="pc-swatch pc-swatch--custom"
        class:pc-swatch--set={custom !== null}
        role="radio"
        aria-checked={custom !== null}
        aria-label={t('project.color.custom')}
        aria-haspopup="dialog"
        data-project-color-custom
        style:--_swatch={custom ?? 'transparent'}
        bind:this={customButton}
        onclick={() => (open = !open)}
    >
        <svg class="pc-swatch__wheel" viewBox="0 0 20 20" aria-hidden="true" focusable="false" data-project-color-wheel>
            {#each WHEEL as w (w.d)}<path d={w.d} fill={w.fill} />{/each}
            <circle cx="10" cy="10" r="3.2" fill="var(--oc-ground-panel)" />
        </svg>
    </button>
    {#if open}
        <ProjectColorPopover initial={startColor} {t} anchor={customButton} onOk={commit} onCancel={() => (open = false)} {onPreview} />
    {/if}
</div>

<style>
    @layer components {
        .pc-swatches {
            display: flex;
            flex-wrap: wrap;
            gap: var(--oc-space-1);
        }

        .pc-swatch {
            position: relative;
            width: 1.4rem;
            height: 1.4rem;
            padding: 0;
            border: 1px solid var(--oc-line-frame);
            border-radius: 2px;
            background: var(--_swatch);
            cursor: pointer;
        }

        .pc-swatch:hover {
            border-color: var(--oc-text-secondary);
        }

        .pc-swatch[aria-checked='true'] {
            border-color: var(--oc-text-bright);
            box-shadow: inset 0 0 0 1px var(--oc-ground-panel);
        }

        .pc-swatch--none {
            background:
                linear-gradient(
                    to top right,
                    transparent calc(50% - 1px),
                    var(--oc-text-secondary) calc(50% - 1px),
                    var(--oc-text-secondary) calc(50% + 1px),
                    transparent calc(50% + 1px)
                ),
                var(--oc-ground-panel);
        }

        .pc-swatch--custom:not(.pc-swatch--set) {
            border-style: dashed;
            background: var(--oc-ground-panel);
        }

        .pc-swatch__wheel {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            padding: 2px;
            pointer-events: none;
        }
    }
</style>

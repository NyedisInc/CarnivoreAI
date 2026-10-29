
<script lang="ts">
    import { onMount } from 'svelte';
    import { ANIMATION_TYPES, animationTypeOff, setAnimationTypeOff, watchAnimationTypes, type AnimationType } from '../motion/animation-types';
    import { animationsOff, watchMotion } from '../motion/motion';
    import { animationsState } from '../motion/animations-state.svelte';
    import type { Translate } from '../sessions/types';
    import Switch from '../base/Switch.svelte';
    import SwitchControl from './controls/SwitchControl.svelte';
    import type { SettingDef } from './settings-registry';

    interface Props {
        def: SettingDef;
        t: Translate;
    }
    const { def, t }: Props = $props();

    const WHY = ['gpu', 'distraction', 'sensitivity', 'sharing'] as const;

    let off = $state<Set<AnimationType>>(new Set());
    const readOff = (): void => { off = new Set(ANIMATION_TYPES.filter((id) => animationTypeOff(id))); };
    readOff();
    onMount(() => watchAnimationTypes(readOff));

    onMount(() => watchMotion(() => { if (animationsOff() === animationsState.on) animationsState.on = !animationsOff(); }));
</script>

<div class="mp">
    <SwitchControl {def} {t} />
    {#if animationsState.on}
        <div class="mp__types">
            <span class="oc-sub">{t('settings.motion.types.title')}</span>
            <p class="mp__text mp__text--muted">{t('settings.motion.types.body')}</p>
            <div class="oc-grid-3">
                {#each ANIMATION_TYPES as id (id)}
                    <Switch
                        label={t(`settings.motion.types.${id}`)}
                        bind:checked={() => !off.has(id), (next) => setAnimationTypeOff(id, !next)}
                        aria-label={t(`settings.motion.types.${id}`)}
                        data-anim-type={id}
                    />
                {/each}
            </div>
        </div>
    {/if}
    <div class="mp__cols">
        <div class="mp__block">
            <span class="oc-sub">{t('settings.motion.stops.title')}</span>
            <p class="mp__text">{t('settings.motion.stops.body')}</p>
            <p class="mp__text mp__text--muted">{t('settings.motion.stops.kept')}</p>
        </div>
        <div class="mp__block">
            <span class="oc-sub">{t('settings.motion.why.title')}</span>
            <ul class="mp__list">
                {#each WHY as why (why)}
                    <li>{t(`settings.motion.why.${why}`)}</li>
                {/each}
            </ul>
        </div>
    </div>
    <div class="mp__example" data-state={animationsState.on ? 'on' : 'off'}>
        <span class="oc-sub">{t('settings.motion.example.title')}</span>
        <div class="mp__demo" class:mp__demo--still={!animationsState.on} aria-hidden="true">
            <span class="mp__ring"></span>
            <span class="mp__bar"></span>
            <span class="mp__dot"></span>
        </div>
        <p class="mp__text" role="status">{t(animationsState.on ? 'settings.motion.example.on' : 'settings.motion.example.off')}</p>
    </div>
</div>

<style>
    @layer components {
        .mp {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            min-width: 0;
        }

        .mp__cols {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: var(--oc-space-3) var(--oc-space-4);
        }

        .mp__block,
        .mp__types,
        .mp__example {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .mp__text {
            margin: 0;
            color: var(--oc-text-secondary);
            line-height: 1.5;
        }

        .mp__text--muted {
            color: var(--oc-text-muted);
        }

        .mp__list {
            margin: 0;
            padding-left: var(--oc-space-4);
            color: var(--oc-text-secondary);
            line-height: 1.5;
        }

        .mp__example {
            padding-top: var(--oc-space-3);
            box-shadow: inset 0 1px 0 var(--oc-control-line);
        }

        .mp__demo {
            display: flex;
            align-items: center;
            gap: var(--oc-space-4);
            padding: var(--oc-space-3) 0;
        }

        .mp__ring {
            width: 16px;
            height: 16px;
            border: 2px solid var(--oc-control-line);
            border-top-color: var(--oc-green);
            border-radius: 50%;
            animation: mp-spin 1s linear infinite;
        }

        .mp__bar {
            flex: 1;
            min-width: 0;
            height: 2px;
            background: var(--oc-cyan);
            transform-origin: left center;
            animation: mp-pulse 1.6s ease-in-out infinite;
        }

        .mp__dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--oc-green);
            animation: mp-breathe 1.8s ease-in-out infinite;
        }

        .mp__demo--still .mp__ring,
        .mp__demo--still .mp__bar,
        .mp__demo--still .mp__dot {
            animation: none;
        }

        @keyframes mp-spin {
            to { transform: rotate(360deg); }
        }

        @keyframes mp-pulse {
            0%, 100% { transform: scaleX(0.25); opacity: 0.5; }
            50% { transform: scaleX(1); opacity: 1; }
        }

        @keyframes mp-breathe {
            0%, 100% { opacity: 0.35; }
            50% { opacity: 1; }
        }
    }
</style>

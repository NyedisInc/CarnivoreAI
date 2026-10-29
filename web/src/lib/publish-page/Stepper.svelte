
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import type { Translate } from '../sessions/types';
    import './wizard.css';

    interface Props {
        current: 0 | 1 | 2 | 3;
        t: Translate;
    }
    const { current, t }: Props = $props();
    const STEPS = ['check', 'image', 'send', 'review'] as const;
</script>

<ol class="d-steps" aria-label={t('publish.page.next.steps_aria')} data-pp="Stepper">
    {#each STEPS as step, i (step)}
        {@const state = i < current ? 'done' : i === current ? 'now' : 'next'}
        <li class="d-steps__i" data-s={state} aria-current={i === current ? 'step' : undefined}>
            <span class="d-steps__n">{#if state === 'done'}<Icon name="check" size={11} />{:else}{i + 1}{/if}</span><span>{t(`publish.page.step.${step}`)}</span>
        </li>
    {/each}
</ol>

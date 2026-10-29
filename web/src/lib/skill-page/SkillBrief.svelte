
<script lang="ts">
    import { CLAUDE_STATE_KEYS } from '../skills-page/skills-model';
    import type { Translate } from '../sessions/types';
    import { estimateTokens, shapeOf } from './model';
    import StateShape from './StateShape.svelte';

    interface Props {
        name: string;
        state: string;
        description: string;
        triggers: readonly string[];
        tokens: number;
        t: Translate;
    }

    const { name, state, description, triggers, tokens, t }: Props = $props();

    const tokenLine = $derived(
        state === 'on'
            ? t('skp.brief.tokens', { count: tokens })
            : state === 'name-only'
              ? t('skp.brief.tokens_about', { count: estimateTokens(name, '') })
              : t('skp.brief.tokens', { count: 0 }),
    );
</script>

<section class="skp-ctx skp-brief" data-skill-brief data-state={state} aria-label={t('skp.brief.label')}>
    <div class="skp-ctx__head">
        <span class="skp-label">{t('skp.brief.label')}</span>
        <span class="skp-ctx__tag" data-tone={state === 'on' ? 'on' : null}><StateShape name={shapeOf(state)} />{t(CLAUDE_STATE_KEYS[state] ?? 'skills.state.off')}</span>
    </div>
    {#if state === 'on'}
        <div class="skp-ctx__body">
            <p class="skp-ctx__desc" data-skill-description>{description || t('skills.detail.no_description')}</p>
            {#if triggers.length > 0}
                <div class="skp-trig" data-triggers>
                    <span class="skp-label">{t('skp.brief.you_say')}</span>
                    <ul>{#each triggers as phrase (phrase)}<li class="skp-phrase">{phrase}</li>{/each}</ul>
                </div>
            {/if}
        </div>
    {:else if state === 'name-only'}
        <div class="skp-ctx__body"><p class="skp-ctx__eff">{t('skp.brief.name_only', { name })}</p></div>
    {:else if state === 'user-invocable-only'}
        <div class="skp-ctx__body"><p class="skp-ctx__eff">{t('skp.brief.on_demand', { name })}</p></div>
    {/if}
    <div class="skp-ctx__foot" data-skill-tokens-every-turn>{tokenLine}</div>
</section>

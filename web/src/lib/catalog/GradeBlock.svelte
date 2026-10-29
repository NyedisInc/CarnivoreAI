
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import { gradeView } from './grade';
    import type { CatalogGrade } from './types';

    interface Props {
        grade?: CatalogGrade | null;
        t: Translate;
    }

    const { grade = null, t }: Props = $props();

    const view = $derived(gradeView(grade));
</script>

<section class="cat-grade" aria-label={t(SKILL_KEYS.gradeHeading)}>
    <div class="cat-grade__head">
        <span class="cat-grade__heading">{t(SKILL_KEYS.gradeHeading)}</span>
        
        {#if view.shape === 'graded' && view.letter}
            <span class="cat-grade__letter">
                {t(SKILL_KEYS.gradeLetter, { letter: view.letter })}
            </span>
        {/if}
    </div>

    {#if view.shape === 'absent'}
        <p class="cat-grade__note">{t(SKILL_KEYS.gradeAbsent)}</p>
    {:else if view.shape === 'ungraded'}
        
        <p class="cat-grade__note cat-grade__note--out" role="status">
            {t(SKILL_KEYS.gradeUngraded)}
        </p>
    {:else}
        {#if view.checked !== null}
            <!-- could not -->
            <p class="cat-grade__note">
                {t(SKILL_KEYS.gradeChecked, { count: view.checked })}
            </p>
        {/if}

        {#if view.failed.length}
            <p class="cat-grade__heading">{t(SKILL_KEYS.gradeFailedHeading)}</p>
            <ul class="cat-grade__failures">
                {#each view.failed as failure}
                    <li class="cat-grade__failure">
                        <span class="cat-grade__rule">
                            {failure.rule ?? t(SKILL_KEYS.gradeFailureUnnamed)}
                        </span>
                        {#if failure.level}
                            <span class="cat-grade__level">{failure.level}</span>
                        {/if}
                        {#if failure.detail}
                            <span class="cat-grade__detail">{failure.detail}</span>
                        {:else}
                            
                            <span class="cat-grade__detail cat-grade__detail--quiet">
                                {t(SKILL_KEYS.gradeFailureNoDetail)}
                            </span>
                        {/if}
                    </li>
                {/each}
            </ul>
        {:else if !view.failedMalformed}
            <!-- could not be read -->
            <p class="cat-grade__note">{t(SKILL_KEYS.gradeNoFailures)}</p>
        {/if}

        {#if view.notGraded.length}
            <p class="cat-grade__note">
                {t(SKILL_KEYS.gradeNotGraded, { count: view.notGraded.length })}
            </p>
        {/if}

        {#if view.failedMalformed}
            <!-- could not -->
            <p class="cat-grade__note cat-grade__note--out" role="status">
                {t(SKILL_KEYS.gradeFailedMalformed)}
            </p>
        {/if}
    {/if}

    <p class="cat-grade__advisory">{t(SKILL_KEYS.gradeAdvisory)}</p>
</section>

<style>
    .cat-grade {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding: 10px 12px;
        border: 1px solid var(--cat-line);
        border-radius: 4px;
        background: var(--cat-panel);
    }

    .cat-grade__head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
    }

    .cat-grade__heading {
        margin: 4px 0 0;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-grade__letter {
        flex-shrink: 0;
        padding: 1px 6px;
        border: 1px solid var(--cat-line);
        border-radius: 3px;
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-grade__failures {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .cat-grade__failure {
        display: flex;
        gap: 10px;
        align-items: baseline;
        flex-wrap: wrap;
        padding: 4px 0;
        border-top: 1px solid var(--cat-line-quiet);
    }

    .cat-grade__failure:first-child {
        border-top: none;
    }

    .cat-grade__rule {
        flex-shrink: 0;
        min-width: 11ch;
        color: var(--cat-attention);
        font-family: var(--cat-mono);
        font-size: 11px;
        overflow-wrap: anywhere;
    }

    .cat-grade__level {
        flex-shrink: 0;
        color: var(--cat-faint);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-grade__detail {
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .cat-grade__detail--quiet {
        color: var(--cat-muted);
    }

    .cat-grade__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
        line-height: 1.45;
    }

    .cat-grade__note--out {
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
    }

    .cat-grade__advisory {
        margin: 2px 0 0;
        color: var(--cat-faint);
        font-size: 11px;
        line-height: 1.4;
    }

    @media (max-width: 767px) {
        .cat-grade__failure {
            flex-direction: column;
            gap: 2px;
        }

        .cat-grade__rule {
            min-width: 0;
        }
    }
</style>


<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';
    import type { HistogramRow } from './ratings';

    interface Props {
        rows: readonly HistogramRow[];
        t: Translate;
    }

    const { rows, t }: Props = $props();
</script>


        <ul class="rh__bars">
            {#each rows as row}
                <li class="rh__bar">
                    <span class="rh__bar-label">
                        {t(SKILL_KEYS.ratingHistogramRow, {
                            stars: row.stars,
                            count: row.count,
                        })}
                    </span>
                    <span class="rh__bar-track">
                        
                        <span
                            class="rh__bar-fill"
                            style="width: {row.percent}%"
                        ></span>
                    </span>
                </li>
            {/each}
        </ul>

<style>
  @layer components {
    .rh__bars {
        display: flex;
        flex-direction: column;
        gap: 3px;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .rh__bar {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .rh__bar-label {
        flex-shrink: 0;
        min-width: 11ch;
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 11px;
    }

    .rh__bar-track {
        flex: 1;
        height: 6px;
        border-radius: 3px;
        background: var(--cat-raised);
        overflow: hidden;
    }

    .rh__bar-fill {
        display: block;
        height: 100%;
        background: var(--cat-action);
    }
  }
</style>

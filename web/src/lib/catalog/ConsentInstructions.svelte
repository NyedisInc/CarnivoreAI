
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import type { Translate } from '../sessions/types';

    interface Props {
        t: Translate;
        details?: readonly string[];
        more?: number;
    }

    const { t, details = [], more = 0 }: Props = $props();
</script>

<div class="consent" role="note" data-instructions-write-consent>
    <p class="consent__warning">{t(SKILL_KEYS.consentInstructionsWrite)}</p>
    {#each details as detail}
        <p class="consent__detail">{detail}</p>
    {/each}
    {#if more > 0}
        <p class="consent__detail" data-instructions-more>{t(SKILL_KEYS.consentInstructionsMore, { count: more })}</p>
    {/if}
</div>

<style>
  @layer components {
    .consent {
        padding: 8px 10px;
        border: 1px solid var(--oc-yellow);
        border-radius: 4px;
    }

    .consent__detail {
        margin: 4px 0 0;
        color: var(--oc-text-secondary, var(--oc-text-primary));
        font-size: 12px;
        line-height: 1.45;
        overflow-wrap: anywhere;
    }

    .consent__warning {
        margin: 0;
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
    }
  }
</style>


<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Checkbox from '../base/Checkbox.svelte';
    import Fold from '../base/Fold.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import { headlineFromSummary, summarizeFlaggedWarnings } from './flagged-labels';
    import type { StructuredReviewWarning } from './permission-diff';

    interface Props {
        summary?: string | null;
        warningReasons?: readonly string[];
        warnings?: readonly StructuredReviewWarning[];
        accepted?: boolean;
        busy?: boolean;
        requireAck?: boolean;
        onAccept?: (next: boolean) => void;
        t: Translate;
    }

    let {
        summary = null,
        warningReasons = [],
        warnings = [],
        accepted = $bindable(false),
        busy = false,
        requireAck = true,
        onAccept,
        t,
    }: Props = $props();

    let detailsOpen = $state(false);

    const headline = $derived(headlineFromSummary(summary));
    const parsed = $derived(summarizeFlaggedWarnings(warnings, warningReasons, t));
    const hasExtraSummary = $derived(Boolean(summary && headline && summary.trim() !== headline.trim()));
    const hasDetails = $derived(parsed.details.length > 0 || hasExtraSummary);
    const detailCount = $derived(parsed.details.length > 0 ? parsed.details.length : undefined);
</script>

<div class="flagged-box" role="note" data-flagged-warning-box>
    <div class="flagged-box__head">
        <Tag tone="warn" data-flagged-badge>{t(SKILL_KEYS.flaggedBadge)}</Tag>
        <p class="flagged-box__lead" data-flagged-headline>{headline ?? t(SKILL_KEYS.flaggedLead)}</p>
    </div>

    {#if parsed.chips.length > 0}
        <div class="flagged-box__chips" data-flagged-chips>
            {#each parsed.chips as chip (chip.key)}
                <Tag tone={chip.tone}>
                    {chip.count > 1 ? `${chip.label} \u00d7${chip.count}` : chip.label}
                </Tag>
            {/each}
        </div>
    {/if}

    {#if hasDetails}
        <div class="flagged-box__fold" data-flagged-details>
            <Fold label={t(SKILL_KEYS.flaggedDetailsFold)} count={detailCount} bind:open={detailsOpen}>
                <div class="flagged-box__panel">
                    {#if summary}
                        <p class="flagged-box__summary" data-flagged-summary>{summary}</p>
                    {/if}
                    {#if parsed.details.length > 0}
                        <ul class="flagged-box__reasons" data-flagged-reasons>
                            {#each parsed.details as row}
                                <li class="flagged-box__reason">
                                    {#if row.label}
                                        <span class="flagged-box__reason-kind">{row.label}</span>
                                    {/if}
                                    {#if row.file}
                                        <code class="flagged-box__reason-file">{row.file}</code>
                                    {/if}
                                    <span class="flagged-box__reason-text">{row.detail}</span>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </div>
            </Fold>
        </div>
    {/if}

    {#if requireAck}
        <div class="flagged-box__ack">
            <Checkbox
                tone="danger"
                checked={accepted}
                disabled={busy}
                label={t(SKILL_KEYS.flaggedAckLabel)}
                data-flagged-ack
                onchange={(event) => {
                    const next = (event.currentTarget as HTMLInputElement).checked;
                    accepted = next;
                    onAccept?.(next);
                }}
            />
        </div>
    {/if}
</div>

<style>
  @layer components {
    .flagged-box {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding: var(--oc-space-3);
        border: var(--oc-border) solid color-mix(in srgb, var(--oc-yellow) 65%, var(--oc-line-panel));
        border-radius: var(--oc-radius-panel);
        background: color-mix(in srgb, var(--oc-yellow) 6%, var(--oc-ground-field));
        color: var(--oc-text-primary);
    }

    .flagged-box__head {
        display: flex;
        align-items: flex-start;
        gap: var(--oc-space-2);
    }

    .flagged-box__lead {
        margin: 0;
        flex: 1 1 auto;
        min-width: 0;
        font-size: var(--oc-fs-body);
        line-height: var(--oc-lh-body);
        color: var(--oc-text-primary);
        overflow-wrap: anywhere;
    }

    .flagged-box__chips {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-1-5);
    }

    .flagged-box__fold {
        border-top: var(--oc-border) solid var(--oc-line-faint);
        padding-top: var(--oc-space-1);
    }

    .flagged-box__panel {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding-top: var(--oc-space-1);
    }

    .flagged-box__summary {
        margin: 0;
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
        color: var(--oc-text-secondary);
        overflow-wrap: anywhere;
    }

    .flagged-box__reasons {
        margin: 0;
        padding: 0;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1-5);
    }

    .flagged-box__reason {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-0-5);
        padding-left: var(--oc-space-2);
        border-left: var(--oc-border) solid color-mix(in srgb, var(--oc-yellow) 55%, var(--oc-line-faint));
        font-size: var(--oc-fs-label);
        line-height: var(--oc-lh-body);
        overflow-wrap: anywhere;
    }

    .flagged-box__reason-kind {
        color: var(--oc-yellow);
        font-size: var(--oc-fs-micro);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
    }

    .flagged-box__reason-file {
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-micro);
    }

    .flagged-box__reason-text {
        color: var(--oc-text-secondary);
    }

    .flagged-box__ack {
        padding-top: var(--oc-space-2);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }
  }
</style>

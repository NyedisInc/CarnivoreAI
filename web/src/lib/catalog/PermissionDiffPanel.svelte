
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Checkbox from '../base/Checkbox.svelte';
    import Tag from '../base/Tag.svelte';
    import type { Translate } from '../sessions/types';
    import {
        PERMISSION_CATEGORY_LABEL_KEYS,
        type PermissionDiffData,
    } from './permission-diff';

    interface Props {
        diff: PermissionDiffData;
        accepted?: boolean;
        busy?: boolean;
        showAck?: boolean;
        onAccept?: (next: boolean) => void;
        t: Translate;
    }

    let {
        diff,
        accepted = $bindable(false),
        busy = false,
        showAck = true,
        onAccept,
        t,
    }: Props = $props();

    const blocked = $derived(diff.provenance.commitShaMismatch);
    const escalationItems = $derived.by(() => {
        const out: string[] = [];
        if (diff.executionEscalation.tier0ToRun) out.push(t(SKILL_KEYS.permDiffTier0ToRun));
        if (diff.executionEscalation.runModeChanged) out.push(t(SKILL_KEYS.permDiffRunMode));
        if (diff.executionEscalation.runCmdChanged) out.push(t(SKILL_KEYS.permDiffRunCmd));
        if (diff.executionEscalation.trustEscalated) out.push(t(SKILL_KEYS.permDiffTrustEscalated));
        return out;
    });
    const oldRef = $derived(
        [diff.provenance.oldRepo, diff.provenance.oldTag].filter(Boolean).join('@') || 'unknown',
    );
    const newRef = $derived(
        [diff.provenance.newRepo, diff.provenance.newTag].filter(Boolean).join('@') || 'unknown',
    );
</script>

<section class="perm-diff" class:perm-diff--blocked={blocked} data-permission-diff>
    <div class="perm-diff__head">
        <p class="perm-diff__title">{t(SKILL_KEYS.permDiffHeading)}</p>
        {#if blocked}
            <Tag tone="danger" data-perm-diff-blocked>{t(SKILL_KEYS.permDiffBlockedNote)}</Tag>
        {:else if diff.executionEscalation.hasAny}
            <Tag tone="danger" data-perm-diff-escalation>{t(SKILL_KEYS.permDiffEscalation)}</Tag>
        {:else if diff.requiresReconsent}
            <Tag tone="warn">{t(SKILL_KEYS.flaggedBadge)}</Tag>
        {/if}
    </div>

    {#if diff.provenance.hasChange}
        <div class="perm-diff__block" class:perm-diff__block--danger={blocked} data-perm-diff-provenance>
            {#if blocked}
                <p class="perm-diff__alert" role="alert">{t(SKILL_KEYS.permDiffCommitMismatch)}</p>
                {#if diff.provenance.oldCommitSha || diff.provenance.newCommitSha}
                    <p class="perm-diff__meta">
                        <code>{diff.provenance.oldCommitSha || 'none'}</code> -> <code>{diff.provenance.newCommitSha || 'none'}</code>
                    </p>
                {/if}
            {:else}
                <p class="perm-diff__meta">
                    {t(SKILL_KEYS.permDiffProvenanceChanged, { oldRef, newRef })}
                </p>
            {/if}
        </div>
    {/if}

    {#if escalationItems.length > 0}
        <div class="perm-diff__block perm-diff__block--danger" data-perm-diff-escalations>
            <p class="perm-diff__label">{t(SKILL_KEYS.permDiffEscalation)}</p>
            <ul class="perm-diff__list">
                {#each escalationItems as item}
                    <li class="perm-diff__item perm-diff__item--add">+ {item}</li>
                {/each}
            </ul>
        </div>
    {/if}

    {#each diff.categories as cat (cat.category)}
        <div class="perm-diff__block" data-perm-diff-cat={cat.category}>
            <p class="perm-diff__label">{t(PERMISSION_CATEGORY_LABEL_KEYS[cat.category])}</p>
            <ul class="perm-diff__list">
                {#each cat.added as entry}
                    <li class="perm-diff__item perm-diff__item--add">
                        <Tag tone="warn">{t(SKILL_KEYS.permDiffAdded)}</Tag>
                        <span>+ {entry}</span>
                    </li>
                {/each}
                {#each cat.removed as entry}
                    <li class="perm-diff__item perm-diff__item--rem">
                        <Tag tone="neutral">{t(SKILL_KEYS.permDiffRemoved)}</Tag>
                        <span>- {entry}</span>
                    </li>
                {/each}
            </ul>
        </div>
    {/each}

    {#if showAck && diff.requiresReconsent && !blocked}
        <div class="perm-diff__ack">
            <Checkbox
                tone="danger"
                checked={accepted}
                disabled={busy}
                label={t(SKILL_KEYS.permDiffAckLabel)}
                data-perm-diff-ack
                onchange={(event) => {
                    const next = (event.currentTarget as HTMLInputElement).checked;
                    accepted = next;
                    onAccept?.(next);
                }}
            />
        </div>
    {/if}
</section>

<style>
  @layer components {
    .perm-diff {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        padding: var(--oc-space-2) var(--oc-space-3);
        border: var(--oc-border) solid var(--oc-yellow);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-field);
    }

    .perm-diff--blocked {
        border-color: var(--oc-coral);
    }

    .perm-diff__head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-2);
    }

    .perm-diff__title {
        margin: 0;
        font-size: var(--oc-fs-label);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
        color: var(--oc-text-primary);
    }

    .perm-diff__block {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        padding-top: var(--oc-space-1-5);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .perm-diff__block--danger {
        border-top-color: var(--oc-coral);
    }

    .perm-diff__label,
    .perm-diff__meta,
    .perm-diff__alert {
        margin: 0;
        font-size: var(--oc-fs-micro);
        line-height: var(--oc-lh-body);
    }

    .perm-diff__label {
        color: var(--oc-text-muted);
        text-transform: uppercase;
        letter-spacing: var(--oc-tracking-label);
    }

    .perm-diff__alert {
        color: var(--oc-coral);
    }

    .perm-diff__meta {
        color: var(--oc-text-secondary);
        overflow-wrap: anywhere;
    }

    .perm-diff__list {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .perm-diff__item {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--oc-space-1-5);
        font-size: var(--oc-fs-body);
        overflow-wrap: anywhere;
    }

    .perm-diff__item--add {
        color: var(--oc-yellow);
    }

    .perm-diff__item--rem {
        color: var(--oc-text-muted);
    }

    .perm-diff__ack {
        padding-top: var(--oc-space-1-5);
        border-top: var(--oc-border) solid var(--oc-line-faint);
    }
  }
</style>

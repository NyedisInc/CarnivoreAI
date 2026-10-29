
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { UpdateDiff } from './types';

    interface Props {
        diff: UpdateDiff;
        t: Translate;
    }

    const { diff, t }: Props = $props();

    function lineClass(line: string): string {
        if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) return 'udiff__line--meta';
        if (line.startsWith('+')) return 'udiff__line--add';
        if (line.startsWith('-')) return 'udiff__line--del';
        return '';
    }
</script>

<section class="udiff" data-update-diff aria-label={t('skill.diff.label')}>
    <p class="udiff__heading">
        {t('skill.diff.heading', { from: diff.from_version, to: diff.to_version })}
    </p>
    {#if diff.changes.length === 0}
        <p class="udiff__none" data-diff-none>{t('skill.diff.none')}</p>
    {/if}
    
    {#each diff.changes as change}
        <div class="udiff__file" data-diff-file={change.path} data-diff-status={change.status}>
            <p class="udiff__head">
                <span class="udiff__status udiff__status--{change.status}">{t(`skill.diff.${change.status}`)}</span>
                <span class="udiff__path">{change.path}</span>
                <span class="udiff__size">
                    {#if change.status === 'changed'}
                        {t('skill.diff.size_changed', { from: change.old_size ?? 0, to: change.new_size ?? 0 })}
                    {:else}
                        {t('skill.diff.size', { count: (change.status === 'added' ? change.new_size : change.old_size) ?? 0 })}
                    {/if}
                </span>
            </p>
            {#if change.diff}
                <pre class="udiff__text" data-diff-text>{#each change.diff.split('\n') as line}<span class="udiff__line {lineClass(line)}">{line}
</span>{/each}</pre>
                {#if change.diff_truncated}
                    <p class="udiff__note">{t('skill.diff.truncated')}</p>
                {/if}
            {:else if change.diff_reason}
                <p class="udiff__note" data-diff-reason={change.diff_reason}>{t(`skill.diff.reason.${change.diff_reason}`)}</p>
            {/if}
        </div>
    {/each}
    {#if diff.unchanged > 0}
        <p class="udiff__note">{t('skill.diff.unchanged', { count: diff.unchanged })}</p>
    {/if}
</section>

<style>
    .udiff {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .udiff__heading {
        margin: 0;
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .udiff__file {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding-top: 6px;
        border-top: 1px solid var(--oc-line-rule);
    }

    .udiff__head {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: baseline;
        margin: 0;
        font-family: var(--font-mono);
        font-size: 11px;
    }

    .udiff__status {
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: 10px;
    }

    .udiff__status--added {
        color: var(--oc-green);
    }

    .udiff__status--removed {
        color: var(--oc-coral);
    }

    .udiff__status--changed {
        color: var(--oc-orange);
    }

    .udiff__path {
        color: var(--oc-text-primary);
        overflow-wrap: anywhere;
    }

    .udiff__size,
    .udiff__note,
    .udiff__none {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: 11px;
    }

    .udiff__text {
        max-height: 200px;
        overflow: auto;
        margin: 0;
        padding: 6px 8px;
        border: 1px solid var(--oc-line-rule);
        border-radius: 4px;
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    .udiff__line--add {
        color: var(--oc-green);
    }

    .udiff__line--del {
        color: var(--oc-coral);
    }

    .udiff__line--meta {
        color: var(--oc-text-muted);
    }

    @media (max-width: 767px) {
        .udiff__text {
            max-height: 30vh;
        }
    }
</style>

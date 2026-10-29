
<script lang="ts">
    import ChoiceDropdown from '../dropdown/ChoiceDropdown.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import { LAUNCH_MARK_PX, LAUNCH_MARK_PX_COMPACT, providerMark, wrapperMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import type { PickerRow } from './picker-model';

    interface Props {
        rows: readonly PickerRow[];
        value?: string;
        onchange?: (value: string) => void;
        compact?: boolean;
        label?: string;
        t?: Translate;
    }
    let { rows, value = $bindable(''), onchange, compact = false, label = '', t = appT }: Props = $props();

    const items = $derived(rows.map((r) => ({ id: r.value, label: r.label, disabled: r.disabled, hint: r.hint, r })));
    const size = $derived(compact ? LAUNCH_MARK_PX_COMPACT : LAUNCH_MARK_PX);
    const dataOf = (r: PickerRow): Record<string, string> => Object.fromEntries(Object.entries(r.data).map(([k, v]) => [`data-${k}`, v]));
</script>

<ChoiceDropdown {items} {value} {compact} label={label || t('launch_picker.group')} description={t('launch_picker.dropdown.count', { n: items.length })} placeholder={t('session.restart.picker.why.pick')} {t} dataKey="launch-profile"
    onChange={(id) => { value = id; onchange?.(id); }}>
    {#snippet row(item)}
        {@const r = item.r}
        {@const mark = wrapperMark(r.icon, r.harness, size)}
        <span class="lpd" class:lpd--compact={compact} data-lpd-row={r.value} {...dataOf(r)}>
            <span class="lpd-mark" role="img" aria-label={providerMark(r.harness).label} data-mark-source={mark.source}>{@html mark.svg}</span>
            <span class="lpd-main">
                <span class="lpd-line">
                    <span class="lpd-label">{r.label}</span>
                    {#if r.isDefault}<span class="lpd-tag lpd-tag--default" data-lpd-default>{t('launch_picker.default')}</span>{/if}
                    {#each r.tags as tag (tag)}<span class="lpd-tag">{tag}</span>{/each}
                    {#if r.kindTag}<span class="lpd-tag lpd-tag--kind" data-kind={r.kind}>{r.kindTag}</span>{/if}
                    {#if r.badge}<span class="lpd-tag lpd-tag--perm" class:lpd-tag--warn={r.permissions === 'skip_all'} data-lpd-perm={r.permissions}>{r.badge}</span>{/if}
                </span>
                {#if r.account || r.model}<span class="lpd-facts">{r.account} · {r.model}</span>{/if}
                {#if r.detail}<span class="lpd-detail">{r.detail}</span>{/if}
            </span>
        </span>
    {/snippet}
</ChoiceDropdown>

<style>
    @layer components {
        .lpd { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 auto; }

        .lpd-mark { display: inline-flex; flex: none; align-items: center; justify-content: center; width: 24px; height: 24px; line-height: 0; color: var(--oc-text-muted); }

        .lpd--compact .lpd-mark { width: 20px; height: 20px; }

        .lpd-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 auto; }

        .lpd-line { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 6px; min-width: 0; font-size: 12px; color: var(--oc-text-primary); }

        .lpd-label { min-width: 0; overflow-wrap: anywhere; }

        .lpd-facts { min-width: 0; overflow-wrap: anywhere; color: var(--oc-text-muted); font-size: 11px; }

        .lpd-detail { color: var(--oc-text-muted); font-size: 11px; overflow-wrap: anywhere; }

        .lpd-tag { flex: none; padding: 0 5px; border: 1px solid var(--oc-line-rule); border-radius: 2px; color: var(--oc-text-muted); font-size: 10px; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; white-space: nowrap; }

        .lpd-tag--default { border-color: var(--oc-orange); color: var(--oc-orange); }

        .lpd-tag--kind[data-kind="replay"] { border-color: var(--oc-green); color: var(--oc-green); }

        .lpd-tag--kind[data-kind="shell"] { border-color: var(--oc-yellow); color: var(--oc-yellow); }

        .lpd-tag--kind[data-kind="transcript_missing"] { border-color: var(--oc-coral); color: var(--oc-coral); }

        .lpd-tag--warn { border-color: var(--oc-yellow); color: var(--oc-yellow); }
    }
</style>


<script lang="ts">
    import { List, ListRow, State } from '../base';
    import type { Translate } from '../sessions/types';
    import { visibleCommand } from '../settings-page/config-bundle/api';
    import type { DisabledProfile } from './api';

    interface Props {
        rows: readonly DisabledProfile[];
        t: Translate;
    }

    const { rows, t }: Props = $props();
</script>

{#if rows.length > 0}
    <List density="roomy" label={t('launch_profiles.list.disabled_title')}>
        {#snippet children()}
            {#each rows as r, i (i)}
                <ListRow>
                    {#snippet children()}
                        <span class="lp-off" data-lp-disabled={r.id}>
                            <span class="lp-off__name">{visibleCommand(r.label ?? r.id)} <code>{visibleCommand(r.id)}</code></span>
                            <State inline kind="warn" role="none" title={t('launch_profiles.list.disabled', { reason: r.reason })} />
                            {#if r.fallback_default}
                                <span class="lp-off__sub">{t('launch_profiles.list.disabled_fallback', { name: r.fallback_default })}</span>
                            {/if}
                        </span>
                    {/snippet}
                </ListRow>
            {/each}
        {/snippet}
    </List>
{/if}

<style>
  @layer components {
    .lp-off { display: flex; flex-direction: column; gap: var(--oc-space-0-5); min-width: 0; padding-block: var(--oc-space-1); }
    .lp-off__name { min-width: 0; font-size: var(--oc-fs-body); font-weight: 600; overflow-wrap: anywhere; unicode-bidi: isolate; }
    .lp-off__name code { font-family: var(--pl-mono); font-weight: 400; }
    .lp-off__sub { color: var(--pl-dim); font-family: var(--pl-mono); font-size: var(--oc-fs-hint); }
  }
</style>

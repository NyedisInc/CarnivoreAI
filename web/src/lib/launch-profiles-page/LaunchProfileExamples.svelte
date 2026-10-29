
<script lang="ts">
    import { Button, Fold } from '../base';
    import type { Translate } from '../sessions/types';
    import type { Example } from './examples';

    interface Props {
        examples: readonly Example[];
        used?: ReadonlySet<string>;
        open?: boolean;
        t: Translate;
        actionKey?: string;
        doneKey?: string;
        disabled?: boolean;
        onUse: (id: string) => void;
    }
    let { examples, used = new Set<string>(), open = $bindable(false), t, actionKey = 'launch_profiles.example.use', doneKey = 'launch_profiles.example.used', disabled = false, onUse }: Props = $props();

    function sets(ex: Example): string {
        const model = ex.model.mode === 'fixed' ? [ex.harness === 'claude' ? '--model' : '-m', ex.model.value ?? ''] : [];
        return [...model, ...ex.flags].join(' ');
    }
</script>

<div class="lp-examples" data-lp-examples>
    <Fold label={t('launch_profiles.example.title')} count={examples.length} bind:open>
        {#snippet children()}
            <ul class="lp-examples__list">
                {#each examples as ex (ex.id)}
                    <li class="lp-examples__row" data-lp-example={ex.id}>
                        <span class="lp-examples__main">
                            <span class="lp-examples__name">{t(`launch_profiles.template.${ex.id}`)}</span>
                            <span class="lp-examples__text">{t(`launch_profiles.example.${ex.id}`)}</span>
                            {#if sets(ex)}<code class="lp-examples__sets">{sets(ex)}</code>{/if}
                        </span>
                        {#if used.has(ex.id)}
                            <span class="lp-examples__text" data-lp-example-done={ex.id}>{t(doneKey)}</span>
                        {:else}
                            <Button size="sm" {disabled} data-lp-example-use={ex.id} onclick={() => onUse(ex.id)}>{t(actionKey)}</Button>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/snippet}
    </Fold>
</div>

<style>
  @layer components {
    .lp-examples { margin-bottom: var(--oc-space-3); border-bottom: 1px solid var(--oc-line-faint); }
    .lp-examples__list { display: flex; flex-direction: column; margin: 0; padding: 0 0 var(--oc-space-1); list-style: none; }
    .lp-examples__row { display: flex; align-items: center; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; border-top: 1px solid var(--oc-line-faint); }
    .lp-examples__row:first-child { border-top: 0; }
    .lp-examples__main { display: flex; flex-direction: column; gap: var(--oc-space-0-5); min-width: 0; }
    .lp-examples__name { font-size: var(--oc-fs-body); font-weight: 600; color: var(--oc-text-primary); }
    .lp-examples__text { font-size: var(--oc-fs-hint); color: var(--oc-text-muted); overflow-wrap: anywhere; }
    .lp-examples__sets { font-family: var(--font-mono); font-size: var(--oc-fs-hint); color: var(--oc-text-secondary); overflow-wrap: anywhere; }
  }
</style>

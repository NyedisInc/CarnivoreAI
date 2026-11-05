
<script lang="ts">
    import { Checkbox } from '../base';
    import type { Translate } from '../sessions/types';

    interface Props {
        count: number;
        checked?: boolean;
        t: Translate;
    }

    let { count, checked = $bindable(false), t }: Props = $props();
</script>

{#if count > 0}
    <div class="lp-hidden" data-lp-hidden>
        <Checkbox label={t('launch_profiles.list.show_hidden', { count })} bind:checked data-lp-show-hidden />
        <span class="lp-hint-line">{t('launch_profiles.list.show_hidden_hint')}</span>
    </div>
{/if}

<style>
  @layer components {
    .lp-hidden { display: flex; flex-direction: column; gap: var(--oc-space-0-5); padding-bottom: var(--oc-space-2); }
    .lp-hint-line { color: var(--pl-dim); font-size: var(--oc-fs-hint); }
  }
</style>

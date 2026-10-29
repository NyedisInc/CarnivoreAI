
<script lang="ts">
    import { Field } from '../base';
    import Check from '../../opscenter/ui/Check.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        t: Translate;
        name: string;
        pinned: boolean;
    }
    let { t, name = $bindable(), pinned = $bindable() }: Props = $props();
</script>

<div class="lnp" data-launch-name-pin>
    <label class="lnp-label" for="lnp-name">{t('launch_picker.name_label')}</label>
    <Field id="lnp-name" block type="text" spellcheck="false" autocomplete="off" bind:value={name} placeholder={t('launch_picker.name_placeholder')} data-lnp-name />
    <Check id="lnp-pinned" data-lnp-pinned="" label={t('launch_picker.pinned_label')} checked={pinned} onToggle={(next) => (pinned = next)} />
</div>

<style>
  @layer components {
    .lnp { display: flex; flex-direction: column; gap: var(--oc-space-1); min-width: 0; font-family: var(--font-mono); }
    .lnp-label { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; }
    @media (max-width: 767px) {
      .lnp :global([data-lnp-pinned]) { min-height: 44px; }
    }
  }
</style>

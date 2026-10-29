<script lang="ts">
  /* the glance area */
  import SettingsOverlay from '../../opscenter/widgets/chrome/SettingsOverlay.svelte';
  import { manifestById } from '../../opscenter/widgets/core-manifests';
  import { t } from '../i18n/index.svelte';
  import { glanceFor } from './glance';
  import { drawerZone } from './zone-store.svelte';

  let { placement, anchor, onClose }: { placement: string; anchor: HTMLElement | null; onClose: () => void } = $props();

  const stored = $derived(drawerZone.glance.find((one) => one.id === placement) ?? null);
  const manifest = $derived(stored ? (manifestById(stored.widget) ?? null) : null);
  const declared = $derived(stored ? (glanceFor(stored.widget)?.options?.() ?? null) : null);
</script>

{#if stored && manifest && declared}
  <SettingsOverlay
    widgetId={stored.widget}
    title={t(manifest.titleKey)}
    {anchor}
    hasSchema={false}
    placement={{
      schema: declared.schema,
      values: stored.options,
      optionLabel: declared.optionLabel,
      onChange: (key, value) => drawerZone.setGlanceOption(placement, key, value),
      onReset: () => {
        for (const key of Object.keys(stored.options)) drawerZone.setGlanceOption(placement, key, null);
      },
      onClose,
    }}
  />
{/if}

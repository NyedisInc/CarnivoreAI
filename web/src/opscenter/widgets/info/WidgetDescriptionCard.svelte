<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import WidgetThumb from '../../layout-editor/WidgetThumb.svelte';
  import type { WidgetManifest } from '../types';
  import WidgetInfoCard from './WidgetInfoCard.svelte';
  import { widgetDescription } from './widget-description';

  /* the widgets page */
  let { manifest, thumb = true, sizes = false }: { manifest: WidgetManifest; thumb?: boolean; sizes?: boolean } = $props();

  const described = $derived(widgetDescription(manifest));
  const more = $derived([
    {
      label: 'widgets.describe.label.places',
      value: described.places.map((place) => t(`widgets.describe.place.${place}`)).join(', '),
      name: 'places',
    },
    {
      label: 'widgets.describe.label.options',
      value: described.options.length
        ? described.options.map((key) => t(key)).join(', ')
        : t('widgets.describe.options_none'),
      name: 'options',
    },
    {
      label: 'widgets.describe.label.maker',
      value:
        described.maker.kind === 'built-in'
          ? t('widgets.describe.maker.built_in')
          : t('widgets.describe.maker.plugin', { vendor: described.maker.vendor }),
      name: 'maker',
    },
  ]);
</script>

<div class="oc-wdesc" data-widget-description={manifest.id}>
  {#snippet thumbnail()}
    <div class="oc-wdesc-preview" role="img" aria-label={t('widgets.describe.preview', { title: t(manifest.titleKey) })}>
      <WidgetThumb {manifest} wide />
    </div>
  {/snippet}
  <WidgetInfoCard info={described.info} {more} hide={sizes ? [] : ['sizes']} preview={thumb ? thumbnail : undefined} />
</div>

<style>
  @layer components {
    .oc-wdesc {
      min-width: 0;
    }

    .oc-wdesc-preview {
      min-width: 0;
    }
  }
</style>

<script lang="ts">
  import MockBar from '../../lib/widgets-page/settings/MockBar.svelte';
  import MockLayout from '../../lib/widgets-page/settings/MockLayout.svelte';
  import { dockedPx, mockKeys } from '../../lib/widgets-page/settings/mock-model';
  import { resolveBars } from '../../lib/widget-bars/bar-settings.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  const view = resolveBars({ v: 1 });
  const side = mockKeys([{ widget: 'core.files', look: null }, { widget: 'core.notes', look: null }], t);
  const bottom = mockKeys([{ widget: 'core.shell', look: null }], t);
</script>

<MockLayout sidePx={dockedPx('side', view)} bottomPx={dockedPx('bottom', view)} label={t('widgets.settings.edit.label')} {t}>
  <MockBar edge="side" size={view.side.size} keys={side} label={t('widgets.places.right.label')} selected={side[0]?.key ?? ''} />
  <MockBar edge="bottom" size={view.bottom.size} keys={bottom} label={t('widgets.places.bottom.label')} selected="" />
</MockLayout>

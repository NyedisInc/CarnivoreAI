<script lang="ts">
  import ModelPicker from '../../lib/byoai/ModelPicker.svelte';
  import { kindItems } from '../../lib/notifications/destinations/form-logic';
  import type { Kind } from '../../lib/notifications/destinations/api';
  import { t } from '../../lib/i18n/index.svelte';

  const ids = ['slack', 'discord', 'teams', 'telegram', 'ntfy', 'pushover', 'pagerduty', 'sns', 'twilio', 'email', 'webhook'];
  const kinds = ids.map((id) => ({ id, label_key: `notify.kind.${id}` }) as Kind);
  let value = $state('ntfy');
</script>

<div style="max-width: 24rem">
  <ModelPicker {t} items={kindItems(kinds, t)} {value} onChange={(id) => (value = id)} label={t('settings.notify.dest.form.kind')} grouped alpha={false} dataAi="sg-kind" />
</div>

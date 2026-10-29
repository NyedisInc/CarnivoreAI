
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import IconButton from '../base/IconButton.svelte';
  import Button from '../base/Button.svelte';
  import { openAdd, rosterUi, setSettings } from './roster-ui.svelte';
</script>

<Button variant="confirm" data-act="add" onclick={() => openAdd()}>{t('roster.toolbar.add')}</Button>
{#if rosterUi.settings === false}
  <IconButton label={t('roster.sets.title')} icon="gear" iconSize={16} data-roster-key="gear" data-act="settings" aria-expanded="false" onclick={() => setSettings(true)} />
{/if}

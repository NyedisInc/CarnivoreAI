
<script lang="ts">
  import { t } from '../i18n/index.svelte';
</script>

<div class="ap-keys" data-auto-keys>
  <span>
    <kbd>&#8593;</kbd><kbd>&#8595;</kbd> {t('automations.page.keys.walk')}
    <kbd>{t('automations.page.keys.enter')}</kbd> {t('automations.page.keys.opens')}
    <kbd>[</kbd><kbd>]</kbd> {t('automations.page.keys.step')}
    <kbd>{t('automations.page.keys.esc')}</kbd> {t('automations.page.keys.closes')}
  </span>
</div>

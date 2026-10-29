
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import SchedulerLog from './SchedulerLog.svelte';

  function reveal(node: HTMLElement): void {
    const calm = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    node.scrollIntoView({ block: 'nearest', behavior: calm ? 'auto' : 'smooth' });
  }

  let { onClose }: { onClose: () => void } = $props();
</script>

<section class="ap-logdock" use:reveal aria-label={t('automations.page.log.all')} data-automation-log>
  <div class="ap-logdock__h">
    <span class="pl-label">{t('automations.page.log.all')}</span>
    <Button size="sm" data-log-close onclick={onClose}>{t('automations.page.log.close')}</Button>
  </div>
  <SchedulerLog automationId={null} />
</section>


<script lang="ts">
    import IconButton from '../base/IconButton.svelte';
    import { t } from '../i18n/index.svelte';
    import { wakeArm } from './wake-arm.svelte';

    let { name }: { name: string } = $props();

    function focusOnDraw(el: HTMLElement): void { el.focus({ preventScroll: true }); }
</script>

<div class="session-sidebar-row-wake-arm" data-wake-arm role="group" aria-label={t('sidebar.row.wake_arm.armed', { name })}><button type="button" class="modal-btn modal-btn-confirm session-sidebar-row-wake-go" data-wake-arm-go aria-disabled={wakeArm.busy ? 'true' : undefined} aria-label={t('sidebar.row.wake_arm.go_aria', { name })} {@attach focusOnDraw}>{wakeArm.busy ? t('sidebar.row.wake_arm.busy') : t('sidebar.row.wake_arm.go')}</button><IconButton label={t('sidebar.row.wake_arm.cancel_aria', { name })} variant="close" icon="close" data-wake-arm-cancel /></div>

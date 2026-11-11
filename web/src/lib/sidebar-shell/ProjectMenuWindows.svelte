
<script lang="ts">
    import MigrateWizard from '../pack-migrate/MigrateWizard.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { closeMigrate, migrate } from '../pack-migrate/migrate-store.svelte';
    import ProjectToolWindow from '../sessions-page/ProjectToolWindow.svelte';
    import { t } from '../i18n/index.svelte';
    import { projectWindows } from './project-menu-windows.svelte';

    $effect(() => {
        if (projectWindows.migrate && !migrate.target) projectWindows.migrate = false;
    });
</script>

{#snippet noHead()}{/snippet}
{#if projectWindows.migrate && migrate.target}
    <!-- the send-to modal -->
    <ModalShell title={t('pack.migrate.title')} head={noHead} contentClass="popup-focus" onCancel={closeMigrate}><MigrateWizard /></ModalShell>
{/if}
{#if projectWindows.tool}<ProjectToolWindow tool={projectWindows.tool.tool} project={projectWindows.tool.project} {t} onClose={() => (projectWindows.tool = null)} />{/if}

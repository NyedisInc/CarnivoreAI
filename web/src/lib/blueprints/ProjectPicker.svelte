
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { browserCatalogHost } from '../catalog/catalog';

    interface Props {
        value: string | null;
        onChange: (path: string | null) => void;
        id: string;
    }

    let { value, onChange, id }: Props = $props();

    let projects = $state<Array<{ name: string; path: string }>>([]);

    onMount(async () => {
        try {
            const rows = await browserCatalogHost().listProjects();
            projects = rows
                .filter((p): p is typeof p & { path: string } => !!p.path)
                .map((p) => ({ name: p.name || p.path!, path: p.path! }));
        } catch {
            projects = [];
        }
    });
</script>

<select
    {id}
    class="modal-input"
    value={value ?? ''}
    onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value || null)}
>
    
    <option value="">{t('opscenter.nav.projects')}</option>
    {#each projects as project (project.path)}
        <option value={project.path}>{project.name}</option>
    {/each}
</select>

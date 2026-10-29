
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import { browserCatalogHost } from '../catalog/catalog';
    import { Select } from '../base';

    interface Props {
        value: string | null;
        onChange: (path: string | null) => void;
        id: string;
        label: string;
    }

    let { value, onChange, id, label }: Props = $props();

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


<Select
    {id}
    {label}
    value={value ?? ''}
    onchange={(e) => onChange(e.currentTarget.value || null)}
    options={[{ value: '', label: t('opscenter.nav.projects') }, ...projects.map((project) => ({ value: project.path, label: project.name }))]}
/>

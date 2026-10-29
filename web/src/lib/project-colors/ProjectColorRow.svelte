
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import type { ProjectColor } from './palette';
    import ProjectColorSwatches from './ProjectColorSwatches.svelte';

    interface Props {
        value: string;
        id: string;
        t: Translate;
        onPick: (key: ProjectColor) => void;
        allowNone?: boolean;
        onPreview?: (hex: string | null) => void;
    }

    const { value, id, t, onPick, allowNone = false, onPreview }: Props = $props();
</script>

<div class="pc-row" data-project-color-row>
    <span class="pc-row__label" {id}>{t('project.color.label')}</span>
    <ProjectColorSwatches {value} labelledBy={id} {t} {onPick} {allowNone} {onPreview} />
</div>

<style>
    @layer components {
        .pc-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-3);
        }

        .pc-row__label {
            color: var(--oc-orange);
            font-size: var(--oc-fs-micro);
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
    }
</style>

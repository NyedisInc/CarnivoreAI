<!-- the detail pane -->
<script lang="ts">
    import type { Translate } from '../sessions/types';

    interface Props {
        supersededBy: string | null;
        t: Translate;
    }

    const { supersededBy, t }: Props = $props();
</script>

<p class="dep-note" role="status" data-deprecated-note>
    {supersededBy ? t('skill.deprecated.detail_superseded', { by: supersededBy }) : t('skill.deprecated.detail')}
</p>

<style>
  @layer components {
    .dep-note {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-yellow);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 12px;
        line-height: 1.45;
    }
  }
</style>

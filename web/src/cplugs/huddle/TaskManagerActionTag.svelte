<script lang="ts">
  import { t } from '../sdk';
  import type { ReviewAction } from './huddle-review';

  let { action, id }: { action: ReviewAction; id?: number } = $props();
</script>

<span class="tkm-action" data-task-manager-action={action} data-task-manager-action-item={id}>{t(`cplug.huddle.action.${action}`)}</span>

<style>
  @layer components {
    .tkm-action {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 16px;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .tkm-action[data-task-manager-action='push'] {
      color: var(--oc-orange);
    }

    .tkm-action[data-task-manager-action='answer'],
    .tkm-action[data-task-manager-action='unstick'] {
      color: var(--oc-yellow-bright);
    }
  }
</style>

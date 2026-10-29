<script lang="ts">
  import { t } from '../sdk';
  import type { HuddleItem } from './huddle-model';
  import { issueNumber } from './task-manager-github-issue';

  let { item }: { item: HuddleItem } = $props();

  const number = $derived(issueNumber(item.github_issue));
</script>

{#if number && item.github_issue}
  <p class="tkm-issue" data-task-manager-github-issue={item.id}>
    <a class="tkm-issue-link" href={item.github_issue} target="_blank" rel="noopener noreferrer"
       aria-label={t('cplug.huddle.github_issue.open', { number })}>#{number}</a>
  </p>
{/if}

<style>
  @layer components {
    .tkm-issue {
      min-width: 0;
      margin: 0;
      overflow: hidden;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .tkm-issue-link {
      color: inherit;
      text-decoration: none;
    }

    .tkm-issue-link:hover,
    .tkm-issue-link:focus-visible {
      color: var(--oc-text-bright);
      text-decoration: underline;
    }
  }
</style>

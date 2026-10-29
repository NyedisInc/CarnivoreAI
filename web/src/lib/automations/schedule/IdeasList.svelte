
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import type { Targets } from '../api';
  import { cronToWords } from './words-model';
  import { offeredIdeas, type Idea } from './ideas';

  let { targets, onUse }: { targets: Targets; onUse: (idea: Idea) => void } = $props();
  const ideas = $derived(offeredIdeas(targets));
</script>

<div class="w-ideas" data-ideas>
  <Card title={t('automations.simple.ideas.title')} compact headingLevel={3}>
    {#snippet children()}
      <p class="w-ideas__p">{t('automations.simple.ideas.intro')}</p>
      <ul class="w-ideas__can">
        {#each [1, 2, 3, 4] as n (n)}<li>{t(`automations.simple.ideas.can_${n}`)}</li>{/each}
      </ul>
      <p class="w-ideas__p">{t('automations.simple.ideas.outro')}</p>
      <List label={t('automations.simple.ideas.title')}>
        {#each ideas as idea (idea.n)}
          <ListRow wrap primary={t(`automations.simple.ideas.${idea.n}.name`)} secondary={t(`automations.simple.ideas.${idea.n}.what`)}>
            {#snippet below()}<span class="ap-num">{cronToWords(idea.cron) ?? idea.cron} · {t(`automations.simple.kind.${idea.kind}`)}</span>{/snippet}
            {#snippet actions()}
              <Button size="sm" data-w-idea={idea.n} aria-label={t('automations.simple.ideas.use_aria', { name: t(`automations.simple.ideas.${idea.n}.name`) })} onclick={() => onUse(idea)}>{t('automations.simple.ideas.use')}</Button>
            {/snippet}
          </ListRow>
        {/each}
      </List>
    {/snippet}
  </Card>
</div>

<script lang="ts">
  import { openModal, t } from '../../sdk';
  import { Icon, IconButton } from '../../sdk/ui';
  import VisitorsModal from './VisitorsModal.svelte';
  import { unforwarded } from './visitors-api';
  import { followVisitors, type VisitorsFeed } from './visitors-feed.svelte';
  import './visitors.css';

  let { slug }: { slug: string } = $props();

  let feed = $state<VisitorsFeed | null>(null);
  const count = $derived(feed ? unforwarded(feed.rows) : 0);

  $effect(() => {
    const follow = followVisitors(slug);
    feed = follow.feed;
    return follow.stop;
  });
</script>

<IconButton label={count > 0 ? t('cplug.reviewboard.public.visitors.key_count', { count }) : t('cplug.reviewboard.public.visitors.key')} variant="quiet" data-board-visitors-key
            onclick={() => void openModal(VisitorsModal, { slug })}><Icon name="users" size={16} />{#if count > 0}<span class="pbs-vcount" data-board-visitors-count>{count}</span>{/if}</IconButton>

<script lang="ts">
  import { openModal, t } from '../sdk';
  import { IconButton } from '../sdk/ui';
  import ShareLinkModal from './ShareLinkModal.svelte';

  let { slug }: { slug: string } = $props();
</script>

<IconButton label={t('cplug.publicboard.share.key')} icon="globe" variant="quiet" iconSize={16} data-board-share-key
            onclick={() => void openModal(ShareLinkModal, { slug })} />

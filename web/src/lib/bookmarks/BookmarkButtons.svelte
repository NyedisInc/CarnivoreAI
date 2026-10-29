
<script lang="ts">
  import Glyph from '../Glyph.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { t } from '../i18n/index.svelte';
  import { openModal } from '../modal';
  import { sessions } from '../../opscenter/api';
  import BookmarksPanel from './BookmarksPanel.svelte';

  let { sessionName }: { sessionName: string | null } = $props();

  const row = $derived((sessions.data ?? []).find((info) => info.tmux_session === sessionName) ?? null);
  const rowId = $derived(typeof row?.session_row_id === 'number' ? row.session_row_id : null);
  const label = $derived(rowId === null ? t('bookmarks.not_loaded') : t('bookmarks.open'));

  function openPanel(): void {
    if (rowId === null) return;
    void openModal(BookmarksPanel, { rowId, name: row?.label ?? sessionName ?? '' });
  }
</script>

<IconButton {label} variant="quiet" data-bookmarks-open disabled={rowId === null} onclick={openPanel}>
  <Glyph name="bookmark" />
</IconButton>

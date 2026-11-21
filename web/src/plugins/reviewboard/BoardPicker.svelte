<script lang="ts">
  import { t } from '../sdk';
  import { Button, List, ListRow } from '../sdk/ui';
  import type { BoardListRow } from './board-model';

  let { boards, onpick }: { boards: BoardListRow[]; onpick: (slug: string) => void } = $props();
</script>

{#if boards.length === 0}
  <p class="rb-note">{t('cplug.reviewboard.page.no_boards')}</p>
{:else}
  <List label={t('cplug.reviewboard.page.pick')}>
    {#each boards as board (board.slug)}
      <ListRow>
        <Button variant="row" data-board-row={board.slug} onclick={() => onpick(board.slug)}>
          <span class="rb-row-line">
            <span class="rb-row-title">{board.title ?? board.slug}</span>
            <span class="rb-row-meta">{t('cplug.reviewboard.page.board_meta', { revisions: board.revisions, rounds: board.rounds })}</span>
            {#if board.state}<span class="rb-state" data-state={board.state}>{t(`cplug.reviewboard.state.${board.state}`)}</span>{/if}
          </span>
        </Button>
      </ListRow>
    {/each}
  </List>
{/if}

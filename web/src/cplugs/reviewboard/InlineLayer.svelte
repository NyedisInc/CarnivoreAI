<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../sdk';
  import type { BoardSidecar, BoardPrompt } from './board-model';
  import type { GapLayout } from './bridge-host';
  import { estimateRooms, placeBlocks, roomsFromHeights, sameRooms } from './inline-picks-model';
  import PromptRow from './PromptRow.svelte';
  import { answerOf, copyGhost, ghostFor, newDraft, pickOption, setChecked, setPromptNote, setText, type Draft } from './tray-model';

  interface Props {
    sidecar: BoardSidecar;
    prompts: BoardPrompt[];
    spots: GapLayout;
    scale: number;
    draft: Draft | null;
    revisionId: string;
    revisionN: number;
    onedit: (change: (draft: Draft | null) => Draft | null) => void;
    onrooms: (rooms: Record<string, number>) => void;
    onplaced: (ids: string[]) => void;
  }

  let { sidecar, prompts, spots, scale, draft, revisionId, revisionN, onedit, onrooms, onplaced }: Props = $props();

  let heights = $state<Record<string, number>>({});
  let told: Record<string, number> = {};

  const blocks = $derived(placeBlocks(prompts, spots, scale));

  function edit(change: (d: Draft) => Draft): void {
    onedit((d) => change(d ?? newDraft(revisionId)));
  }

  $effect(() => {
    onplaced(blocks.flatMap((b) => b.prompts.map((p) => p.id)));
  });

  $effect(() => {
    const measured = roomsFromHeights(heights, scale);
    const wanted = { ...estimateRooms(prompts), ...measured };
    untrack(() => {
      if (sameRooms(wanted, told)) return;
      told = wanted;
      onrooms(wanted);
    });
  });
</script>

<div class="rb-inline" data-inline-layer role="group" aria-label={t('cplug.reviewboard.inline.label')}>
  {#each blocks as block (block.anchor)}
    <div class="rb-inline-block" data-inline-block={block.anchor} style:left="{block.left}px" style:top="{block.top}px" style:width="{block.width}px"
         bind:offsetHeight={heights[block.anchor]}>
      {#each block.prompts as prompt (prompt.id)}
        {@const ghost = ghostFor(sidecar, prompt, revisionN)}
        <PromptRow {prompt} answer={answerOf(draft, prompt.id)} {ghost} highlighted={false}
                   onpick={(o) => edit((d) => pickOption(d, prompt, o))} oncheck={(c) => edit((d) => setChecked(d, prompt, c))}
                   ontext={(x) => edit((d) => setText(d, prompt, x))} onnote={(x) => edit((d) => setPromptNote(d, prompt, x))}
                   oncopy={() => ghost && edit((d) => copyGhost(d, prompt, ghost))} />
      {/each}
    </div>
  {/each}
</div>

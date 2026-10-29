<script lang="ts">
  import AnchoredPopup from '../../lib/dialog-frame/AnchoredPopup.svelte';
  import ConfirmPopup from '../../lib/dialog-frame/ConfirmPopup.svelte';

  type Open = 'below' | 'question' | null;
  let open = $state<Open>(null);
  let answer = $state('nothing yet');
  let belowAt = $state<HTMLElement | null>(null);
  let askAt = $state<HTMLElement | null>(null);

  function done(why: string): void {
    answer = why;
    open = null;
  }
</script>

<div class="sg-row">
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="anchored-below" bind:this={belowAt}
    aria-haspopup="dialog" aria-expanded={open === 'below'} onclick={() => (open = open === 'below' ? null : 'below')}>below</button>
  <button type="button" class="modal-btn modal-btn-secondary" data-sg-open="anchored-question" bind:this={askAt}
    aria-haspopup="dialog" aria-expanded={open === 'question'} onclick={() => (open = open === 'question' ? null : 'question')}>a question</button>
</div>
<p class="sg-caption">last answer: <code data-sg-answer>{answer}</code></p>

{#if open === 'below'}
  <AnchoredPopup class="sg-anchored" label="layout" anchor={belowAt} onClose={() => done('closed')}>
    <div class="pl-titlebar"><span class="pl-title">layout</span></div>
    <div class="sg-anchored__body">
      <button type="button" class="oc-btn oc-btn--sm" onclick={() => done('fit rows')}>fit rows</button>
      <button type="button" class="oc-btn oc-btn--sm" onclick={() => done('reset layout')}>reset layout</button>
    </div>
  </AnchoredPopup>
{:else if open === 'question'}
  <ConfirmPopup label="move here" message="notes is already here. move it to this spot?" anchor={askAt} cancelLabel="cancel" confirmLabel="move here"
    onConfirm={() => done('moved')} onCancel={() => done('cancelled')} />
{/if}

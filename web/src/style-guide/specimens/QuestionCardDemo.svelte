<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import Card from '../../lib/base/Card.svelte';
  import Field from '../../lib/base/Field.svelte';
  import Fold from '../../lib/base/Fold.svelte';
  import OptionList, { type OptionItem } from '../../lib/base/OptionList.svelte';

  const Q1: OptionItem[] = [
    { value: 'yes', label: 'yes, both stay built in', reason: 'other code depends on them', recommended: true },
    { value: 'no', label: 'no, every writer must become a plugin' },
  ];
  const Q2: OptionItem[] = [
    { value: 'later', label: 'not yet, both ship for one release', reason: 'an upgrade never loses an export it already had', recommended: true },
    { value: 'now', label: 'yes, remove it at once' },
  ];

  let open = $state(true);
  let answer1 = $state('');
  let answer2 = $state('');
  let other = $state('');
  let answerOpen = $state(false);
  const left = $derived([answer1, answer2].filter((a) => !a).length);
</script>

<Card title="question" meta="needs your answer" foldable bind:open>
  {#snippet children()}
    <p>Split off the export item: exports move onto the shared writer, then csv and json output is tested on a sample project.</p>
    <Fold label="answer: move the exports onto the shared writer, then test csv and json output" bind:open={answerOpen}>
      {#snippet children()}
        <p>The design is written. Stage A needs no new code: both writers are reached through one shared interface.</p>
        <p>Stage B adds a third writer behind the same interface.</p>
      {/snippet}
    </Fold>
    <OptionList number={1} prompt="the csv and json writers stay built in. ok?"
      tag="required" options={Q1} recommendedLabel="rec" bind:value={answer1}>
      {#snippet foot()}
        <Button size="sm" onclick={() => (answer1 = 'yes')}>take recommendation</Button>
        <Button size="sm">add a note</Button>
      {/snippet}
    </OptionList>
    <OptionList number={2} prompt="once a writer ships as a plugin, is it also removed from the core?"
      tag="required" options={Q2} recommendedLabel="rec" bind:value={answer2}>
      {#snippet foot()}
        <Button size="sm" onclick={() => (answer2 = 'later')}>take recommendation</Button>
        <Button size="sm">add a note</Button>
      {/snippet}
    </OptionList>
    <Field label="other" placeholder="say it in your words" bind:value={other} />
  {/snippet}
  {#snippet foot()}
    <Button variant="confirm" disabled={left > 0}>submit</Button>
    <span class="oc-card__meta">{left ? `${left} required left` : 'ready to send'}</span>
  {/snippet}
</Card>

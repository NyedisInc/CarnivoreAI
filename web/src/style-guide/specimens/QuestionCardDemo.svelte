<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import Card from '../../lib/base/Card.svelte';
  import Field from '../../lib/base/Field.svelte';
  import Fold from '../../lib/base/Fold.svelte';
  import OptionList, { type OptionItem } from '../../lib/base/OptionList.svelte';

  const Q1: OptionItem[] = [
    { value: 'yes', label: 'yes, those four stay built in', reason: 'core depends on them; packaging them means untangling core first', recommended: true },
    { value: 'no', label: 'no, every plugin must become a package, untangle them too' },
  ];
  const Q2: OptionItem[] = [
    { value: 'later', label: 'not before 1.0, both ship for one release', reason: 'an upgrade never loses a plugin it already had', recommended: true },
    { value: 'now', label: 'yes, remove it from the app at once' },
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
    <p>Split off the plugin design item: plugins move onto the catalog, then install, use and uninstall are tested on
      the test box. Scope depends on which kinds the app can install from the catalog today.</p>
    <Fold label="answer: move the plugins onto the catalog, then test install, use and uninstall" bind:open={answerOpen}>
      {#snippet children()}
        <p>The design is written and on master. Stage A needs no new loading code: every plugin, the built-in themes
          and the bundled skills show up in the catalog through the signed built-ins list.</p>
        <p>Stage B makes a plugin a signed package that loads inside the app under the same id, routes and data
          folder.</p>
      {/snippet}
    </Fold>
    <OptionList number={1} prompt="the task manager, mark unread, share and the widget lab stay compiled in (listed in the catalog as built-ins). ok?"
      tag="required" options={Q1} recommendedLabel="rec" bind:value={answer1}>
      {#snippet foot()}
        <Button size="sm" onclick={() => (answer1 = 'yes')}>take recommendation</Button>
        <Button size="sm">add a note</Button>
      {/snippet}
    </OptionList>
    <OptionList number={2} prompt="once a plugin ships as a catalog package, is it also removed from the app itself?"
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

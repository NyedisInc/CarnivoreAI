<script lang="ts">
  import Accordion from '../../lib/base/Accordion.svelte';
  import Button from '../../lib/base/Button.svelte';
  import Card from '../../lib/base/Card.svelte';
  import Field from '../../lib/base/Field.svelte';
  import Fold from '../../lib/base/Fold.svelte';
  import OptionList, { type OptionItem } from '../../lib/base/OptionList.svelte';
  import Tag from '../../lib/base/Tag.svelte';
  import List, { type ListDensity } from '../../lib/base/List.svelte';
  import MenuItem from '../../lib/base/MenuItem.svelte';
  import ListRow from '../../lib/base/ListRow.svelte';
  import Toolbar from '../../lib/base/Toolbar.svelte';
  import State from '../../lib/base/State.svelte';
  import StatusLed from '../../lib/StatusLed.svelte';
  import SearchField from '../../opscenter/ui/SearchField.svelte';
  import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';

  const OPTIONS: OptionItem[] = [
    { value: 'pg', label: 'postgres', reason: 'the one the team already runs', recommended: true },
    { value: 'sqlite', label: 'sqlite', reason: 'a single file, no server to keep up' },
    { value: 'none', label: 'no database yet', disabled: true },
  ];
  const GROUPS = [
    { value: 'running', label: 'running', count: 3 },
    { value: 'waiting', label: 'waiting on you', count: 1 },
    { value: 'done', label: 'done', count: 12 },
  ];
  const DENSITIES: ListDensity[] = ['dense', 'default', 'roomy'];
  const ROWS = [
    { name: 'nightly backup', when: 'every day at 02:00', took: '12s', status: 'idle' },
    { name: 'deploy check', when: 'every 15 minutes', took: '1m 04s', status: 'working' },
    { name: 'weekly report with a long name that gives way first', when: 'mondays at 09:00', took: '3s', status: 'question' },
  ];
  const STATUS_OPTIONS = [
    { value: '', label: 'all' },
    { value: 'failed', label: 'failed' },
  ];
  let query = $state('');
  let facet = $state('');
  let selectedRow = $state('deploy check');
  let single = $state('pg');
  let several = $state<string[]>(['pg']);
</script>

<div class="sg-bc">
  <div class="sg-bc__group">
    <span class="sg-bc__label">button: secondary, confirm, danger, quiet; sm; disabled; link</span>
    <div class="sg-row">
      <Button>cancel</Button>
      <Button variant="confirm">save</Button>
      <Button variant="danger">remove</Button>
      <Button variant="quiet">details</Button>
      <Button disabled>disabled</Button>
      <Button href="#base-set">a link</Button>
    </div>
    <div class="sg-row">
      <Button size="sm">stop</Button>
      <Button size="sm" variant="confirm">run</Button>
      <Button size="sm" variant="danger">remove</Button>
      <Button size="sm" variant="quiet">add a note</Button>
    </div>
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">tag: neutral, accent, ok, warn, danger, info</span>
    <div class="sg-row">
      <Tag>required</Tag><Tag tone="accent">new</Tag><Tag tone="ok">rec</Tag><Tag tone="warn">stale</Tag>
      <Tag tone="danger">failed</Tag><Tag tone="info">beta</Tag>
    </div>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">field: plain, help, error, multiline, disabled</span>
    <Field label="name" placeholder="a short name" />
    <Field label="folder" value="~/carnivore-projects/api" help="the project's folder on this computer" />
    <Field label="port" value="5000" error="5000 is taken by the system; pick 5001 or above" />
    <Field label="note" multiline placeholder="anything else" />
    <Field label="token" value="locked" disabled />
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">field, search variant: empty with a key hint, holding text (the x shows unfocused, no hover tile), with a trailing slot; similar terms under it</span>
    <Field variant="search" label="search agents" placeholder="search agents" hint="/" clearLabel="clear search" />
    <Field variant="search" label="search agents" value="carn" hintFilled="esc" clearLabel="clear search" />
    <Field variant="search" label="search agents" value="carn" hintFilled="esc" clearLabel="clear search">
      {#snippet lead()}in: crate{/snippet}
      {#snippet trailing()}<Button size="sm" variant="quiet" aria-label="search mode: names">names</Button>{/snippet}
    </Field>
    <div class="sg-row" role="listbox" aria-orientation="horizontal" aria-label="similar terms">
      <Tag>similar</Tag>
      <Button size="sm" role="option" aria-selected="false">carnivore <Tag tone="info">41</Tag></Button>
      <Button size="sm" role="option" aria-selected="true">carnival <Tag tone="info">6</Tag></Button>
      <Button size="sm" role="option" aria-selected="false">carnage <Tag tone="info">2</Tag></Button>
    </div>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">option list: one choice, several</span>
    <OptionList number={1} prompt="which database?" tag="required" options={OPTIONS} recommendedLabel="rec" bind:value={single} />
    <OptionList number={2} prompt="which checks run before a deploy?" tag="optional" multiple options={OPTIONS} recommendedLabel="rec" bind:value={several} />
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">fold and accordion</span>
    <Fold label="details" count={2}>
      {#snippet children()}<p>the panel of a fold: no frame of its own, the container's left edge.</p>{/snippet}
    </Fold>
    <Accordion items={GROUPS} type="single" value="waiting">
      {#snippet panel(item)}<p>{item.label}: rows would sit here.</p>{/snippet}
    </Accordion>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">list: dense 22 (icon actions), default 26, roomy 32; lead, meta, a selected row; actions always shown</span>
    {#each DENSITIES as density (density)}
      <List {density} label="automations, {density}">
        {#each ROWS as r (r.name)}
          <ListRow primary={r.name} secondary={r.when} meta={r.took} selected={selectedRow === r.name}
            tabindex={0} onclick={() => (selectedRow = r.name)}>
            {#snippet lead()}<StatusLed status={r.status} unread={false} startupGate={null} statusSource={null} transport={null} />{/snippet}
            {#snippet actions()}
              {#if density === 'dense'}
                <button type="button" class="oc-ibtn oc-ibtn--bare" aria-label="run {r.name}">
                  <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3l8 5-8 5z" fill="currentColor" /></svg>
                </button>
              {:else}
                <Button size="sm" variant="confirm">run</Button><Button size="sm" variant="quiet">edit</Button>
              {/if}
            {/snippet}
          </ListRow>
        {/each}
      </List>
    {/each}
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">menu item: the item menu's row look, enabled with a key word and a reason line, then disabled (the reason is the tooltip)</span>
    <div class="session-row-menu" role="group" aria-label="menu item specimen" style="position: static; z-index: auto">
      <MenuItem label="add to home" keyHint="widget" reason="goes in the first free slot" />
      <MenuItem label="add to work" disabled reason="already in this place" />
    </div>
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">list row, disabled (aria-disabled="true"): dimmed through tokens, no pointer action</span>
    <List density="roomy" label="disabled specimen">
      <ListRow primary="restore from backup" secondary="needs a connected drive" aria-disabled="true" onclick={() => {}} />
      <ListRow primary="open the folder" secondary="available" onclick={() => {}} />
    </List>
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">list row with a below block: one head line (lead, name, meta, actions), the excerpt under it at the full row width, wrapping, nothing changes on hover</span>
    <List density="roomy" label="below specimen">
      <ListRow primary="release notes review" meta="you, 3h">
        {#snippet lead()}<StatusLed status="idle" unread={false} startupGate={null} statusSource={null} transport={null} />{/snippet}
        {#snippet actions()}<button type="button" class="oc-ibtn oc-ibtn--bare" aria-label="open release notes review"><svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3l8 5-8 5z" fill="currentColor" /></svg></button>{/snippet}
        {#snippet below()}can you re-run the restic backup against the offsite target and tell me whether the snapshot count matches what we had before the move, the whole excerpt shows and wraps at the row's edge{/snippet}
      </ListRow>
    </List>
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">toolbar: band (search, filters, end, pills below); plain, as it sits in a page bar</span>
    <Toolbar band wrap role="search" label="automations list">
      {#snippet search()}<SearchField value={query} onInput={(v) => (query = v)} placeholder="find" />{/snippet}
      {#snippet filters()}<FacetSelect id="status" label="status" value={facet} options={STATUS_OPTIONS} onChange={(v) => (facet = v)} />{/snippet}
      {#snippet end()}<span class="oc-titlebar__sub">3 of 9 automations</span>{/snippet}
      {#snippet below()}<Tag tone="accent">last run: failed</Tag><Tag>kind: command</Tag>{/snippet}
    </Toolbar>
    <Toolbar label="plugins">
      {#snippet search()}<SearchField value={query} onInput={(v) => (query = v)} placeholder="find a plugin" />{/snippet}
      {#snippet end()}<Button size="sm" variant="quiet">sort: name</Button>{/snippet}
    </Toolbar>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">state: empty with actions, loading, error with retry, inline</span>
    <State title="no automations yet" hint="start from a template, or make your own">
      {#snippet actions()}<Button size="sm" variant="confirm">new automation</Button><Button size="sm">keep awake</Button>{/snippet}
    </State>
    <State kind="loading" title="reading the list" />
    <State kind="error" title="could not read the automations: the server did not answer" onAction={() => {}} actionLabel="try again" />
    <State inline title="nothing matches the filters" actionLabel="clear filters" onAction={() => (facet = '')} />
  </div>

  <div class="sg-bc__cards">
    <Card title="cloudecode" meta="3 running">
      {#snippet children()}<p>a plain card: raised surface, surface edge, panel corner, one border.</p>{/snippet}
    </Card>
    <Card title="argent" meta="compact" compact>
      {#snippet children()}<p>a compact card: the small padding step.</p>{/snippet}
    </Card>
    <Card title="keep awake" meta="foldable" foldable>
      {#snippet actions()}<Button size="sm" variant="quiet">edit</Button>{/snippet}
      {#snippet children()}<p>a foldable card: the title is the fold button, actions stay outside it.</p>{/snippet}
      {#snippet foot()}<Button size="sm">cancel</Button><Button size="sm" variant="confirm">save</Button>{/snippet}
    </Card>
    <Card aria-label="a card with no title">
      {#snippet children()}<p>an untitled card: no title strip, just the bordered body (a screen passes aria-label).</p>{/snippet}
    </Card>
    <Card title="a long card title that would be crushed to a few letters by its actions" meta="wrapping actions">
      {#snippet actions()}<Button size="sm" variant="quiet">edit</Button><Button size="sm" variant="quiet">duplicate</Button><Button size="sm" variant="quiet">export</Button><Button size="sm" variant="quiet">archive</Button>{/snippet}
      {#snippet children()}<p>the title keeps its width and ellipsizes; the actions wrap to a second line inside the strip when the line runs out.</p>{/snippet}
    </Card>
  </div>
</div>

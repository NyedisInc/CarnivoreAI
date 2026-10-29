<script lang="ts">
  import IconButton from '../../lib/base/IconButton.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';
  import NumberField from '../../lib/base/NumberField.svelte';
  import Segmented from '../../lib/base/Segmented.svelte';
  import Select from '../../lib/base/Select.svelte';
  import Radio from '../../lib/base/Radio.svelte';
  import RadioGroup from '../../lib/base/RadioGroup.svelte';
  import Switch from '../../lib/base/Switch.svelte';

  let pressed = $state(true);
  let sounds = $state(true);
  let quiet = $state(false);
  let beta = $state(true);
  let mixed = $state(true);
  let dest = $state('project');
  let size = $state('b');
  let theme = $state('dark');
  let kind = $state('');
  let scope = $state('sessions');
  let density = $state('default');
  let topN = $state<number | null>(5);
  let ratio = $state<number | null>(0.2);
</script>

<div class="sg-bc">
  <div class="sg-bc__group">
    <span class="sg-bc__label">icon button: framed, pressed toggle, disabled; quiet, open; close; float; 24 and 32 squares</span>
    <div class="sg-row">
      <IconButton label="move up" icon="chevron-up" />
      <IconButton label="pin" icon="pin" pressed={pressed} onclick={() => (pressed = !pressed)} />
      <IconButton label="move down" icon="chevron-down" disabled />
      <IconButton label="more" icon="menu" variant="quiet" />
      <IconButton label="filters (open)" icon="settings" variant="quiet" aria-expanded="true" />
      <IconButton label="close" icon="close" variant="close" />
      <IconButton label="open in a window" icon="external" variant="float" />
      <IconButton label="pin" tooltip="pin this to the top (p)" icon="pin" />
      <IconButton label="add" icon="plus" style="--oc-ibtn-size: var(--oc-control-h-sm)" />
      <IconButton label="add" icon="plus" style="--oc-ibtn-size: var(--oc-control-h)" />
    </div>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">switch: off, on, with a hint, with a note, disabled, no frame (bare)</span>
    <Switch label="sounds" bind:checked={sounds} />
    <Switch label="quiet hours" hint="no tones between 22:00 and 07:00" bind:checked={quiet} />
    <Switch label="auto sleep" note="new" checked />
    <Switch label="beast mode" disabled />
    <Switch label="locked on" checked disabled />
    <Switch label="show system sessions" bare bind:checked={quiet} />
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">checkbox: off, on, mixed, with a hint, disabled; radio group: vertical with a hint and a disabled option, horizontal</span>
    <Checkbox label="enabled" bind:checked={beta} />
    <Checkbox label="select all" bind:indeterminate={mixed} checked={false} />
    <Checkbox label="send a summary" hint="one message when the run ends" />
    <Checkbox label="locked on" checked disabled />
    <Checkbox label="a long label that wraps onto a second line on a phone: the mark stays beside the first line, never mid-block" checked />
    <RadioGroup label="destination" bind:value={dest}
      options={[{ value: 'project', label: 'in a project', hint: 'the folder moves with it' }, { value: 'folder', label: 'in a folder' }, { value: 'none', label: 'nowhere yet', disabled: true }]} />
    <RadioGroup label="size" orientation="horizontal" bind:value={size}>
      <Radio value="a" label="small" /><Radio value="b" label="medium" /><Radio value="c" label="large" />
    </RadioGroup>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">select: labelled with help, error, disabled; bare small (a bar filter); grouped</span>
    <Select label="theme" bind:value={theme} help="applies to every session without its own"
      options={[{ value: 'dark', label: 'carnivore' }, { value: 'light', label: 'carnivore light' }, { value: 'amber', label: 'amber phosphor' }]} />
    <Select label="shell" error="pick a shell that is installed" options={[{ value: '', label: 'choose...' }, { value: 'zsh', label: 'zsh' }]} />
    <Select label="locked" disabled value="a" options={[{ value: 'a', label: 'fixed by policy' }]} />
    <div class="sg-row">
      <Select size="sm" aria-label="kind filter" bind:value={kind}
        options={[{ value: '', label: 'all kinds' }, { value: 'chart', label: 'chart' }, { value: 'note', label: 'note' }]} />
      <Select aria-label="grouped" value="a" options={[{ group: 'live', options: [{ value: 'a', label: 'running' }] }, { group: 'done', options: [{ value: 'b', label: 'finished' }] }]} />
    </div>
  </div>

  <div class="sg-bc__group sg-bc__fields">
    <span class="sg-bc__label">number field: with stepper (min 1, max 10), decimal step, plain with an error, small, disabled</span>
    <NumberField label="rows shown" min={1} max={10} stepper bind:value={topN} help="arrow keys step too" />
    <NumberField label="ratio" min={0} max={1} step={0.1} stepper bind:value={ratio} />
    <NumberField label="port" value={5000} error="5000 is taken by the system" />
    <NumberField size="sm" stepper aria-label="retries" value={3} min={0} max={9} />
    <NumberField label="locked" value={2} disabled stepper />
  </div>

  <div class="sg-bc__group">
    <span class="sg-bc__label">segmented: picked, a disabled option, icons, md, fill; arrows move and choose, one tab stop</span>
    <div class="sg-row">
      <Segmented label="scope" bind:value={scope}
        options={[{ value: 'global', label: 'global' }, { value: 'sessions', label: 'sessions' }, { value: 'both', label: 'both' }]} />
      <Segmented label="density" bind:value={density}
        options={[{ value: 'dense', label: 'dense' }, { value: 'default', label: 'default' }, { value: 'roomy', label: 'roomy', disabled: true }]} />
      <Segmented label="view" value="list" options={[{ value: 'list', label: 'list', icon: 'menu' }, { value: 'grid', label: 'grid', icon: 'settings' }]} />
    </div>
    <div class="sg-row">
      <Segmented label="per-option title" value="a" options={[{ value: 'a', label: 'all', title: 'every session' }, { value: 'b', label: 'mine', title: 'only sessions you started' }]} />
      <Segmented label="size, md" size="md" value="b" options={[{ value: 'a', label: 'small' }, { value: 'b', label: 'medium' }, { value: 'c', label: 'large' }]} />
    </div>
    <Segmented label="fill" fill value="b" options={[{ value: 'a', label: 'low' }, { value: 'b', label: 'medium' }, { value: 'c', label: 'high' }]} />
  </div>
</div>

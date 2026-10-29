<script lang="ts">
  import { t } from '../sdk';
  import { ALL_LIST, isAgentList, type TaskManagerSession } from './huddle-model';
  import { START_NEW, STOP } from './task-manager-send-start';

  let { list, sessions, value, label, title, onPick, cls = '', ...rest }: {
    list: string;
    sessions: readonly TaskManagerSession[];
    value: string;
    label: string;
    title?: string;
    onPick: (value: string) => void;
    cls?: string;
    [attr: `data-${string}`]: string | undefined;
  } = $props();
</script>

<select class={cls} data-field data-size="sm" {value} aria-label={label} {title} data-task-manager-target-pick={list} {...rest}
        onchange={(event) => onPick((event.currentTarget as HTMLSelectElement).value)}>
  <option value="">{t('cplug.huddle.send.target_none')}</option>
  {#if list !== ALL_LIST && !isAgentList(list)}<option value={START_NEW} data-task-manager-target-new>{t('cplug.huddle.send.target_new')}</option>{/if}
  {#each sessions as session (session.id)}<option value={session.id}>{session.label}</option>{/each}
  <option value={STOP} data-task-manager-target-stop>{t('cplug.huddle.send.target_stop')}</option>
</select>

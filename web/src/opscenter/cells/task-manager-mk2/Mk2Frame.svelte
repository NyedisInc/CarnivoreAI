<script lang="ts">
  /* padding */
  import { setContext, untrack, type Snippet } from 'svelte';
  import { DETAIL_SLOT } from '../../../cplugs/huddle/task-manager-detail-slot';
  import { BODY_OPTIONS, type BodyOptions } from '../../../cplugs/huddle/task-manager-body-options';
  import { TAGGED_OPEN, type TaggedOpener } from '../../../cplugs/huddle/task-manager-tagged-open';
  import { openSession } from '../../api';
  import { sessionIdForUuid } from '../../../lib/open-files/session-ref';
  import Mk2TaskTabs from './Mk2TaskTabs.svelte';
  import { MK2_VIEW, type Mk2ViewHolder } from './mk2-view-context';
  import { effectiveState } from './mk2-task-state';
  import { viewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
  import type { TaskState } from '../../../lib/base/task-wrapper';

  let { projectColors, statusBar, taskState, view, children }: { projectColors: boolean; statusBar: boolean; taskState: TaskState; view: Mk2ViewHolder; children: Snippet } = $props();

  const openTagged: TaggedOpener = (sessionUuid) => {
    void sessionIdForUuid(sessionUuid).then((id) => { if (id) openSession(id, null); });
  };

  setContext(DETAIL_SLOT, Mk2TaskTabs);
  setContext<Mk2ViewHolder>(MK2_VIEW, untrack(() => view));
  setContext<TaggedOpener>(TAGGED_OPEN, openTagged);
  setContext<BodyOptions>(BODY_OPTIONS, { get taskState() { return effectiveState(taskState, viewFilter.chip); }, completedKeys: false, sendInAddRow: true, issueLink: false, tabbedDetail: true, replySplit: true, subtasks: false, drawerIcons: true, taskWrapper: true, baseFields: true, holdWhileLooking: true, scheduleBlocks: false });
</script>

<div class="mk2-frame" data-mk2-frame data-base-fields data-mk2-project-colors={projectColors ? 'on' : 'off'} data-mk2-status-bar={statusBar ? 'on' : 'off'}>
  {@render children()}
</div>

<style>
  @layer components {
    .mk2-frame {
      --mk2-pc: 0px;
      --mk2-sb: 0px;
      --mk2-row-indent: 18px;
      --mk2-head-indent: 4px;
      --mk2-sub-indent: 14px;
      --mk2-chev-indent: 10px;
      --mk2-stripe-left: 5px;
      display: contents;
    }

    .mk2-frame[data-mk2-project-colors='off'] {
      --mk2-pc: 3px;
    }

    .mk2-frame[data-mk2-status-bar='off'] {
      --mk2-sb: 10px;
    }

    .mk2-frame :global(:is(input, select, textarea)[data-field]) {
      height: revert-layer;
      min-height: revert-layer;
      padding: revert-layer;
      border: revert-layer;
      border-radius: revert-layer;
      background: revert-layer;
      color: revert-layer;
      font: revert-layer;
      line-height: revert-layer;
    }

    .mk2-frame :global(:is(input, select, textarea)[data-field][data-size='sm']) {
      min-height: var(--oc-control-h-sm);
      font-size: var(--oc-fs-label);
    }

    /*  hidden  */
    .mk2-frame:is([data-mk2-project-colors='off'], [data-mk2-status-bar='off']) :global(.hdr:not(.hdr--wrapped)) {
      padding-left: calc(var(--mk2-row-indent) - var(--mk2-pc) - var(--mk2-sb));
    }

    .mk2-frame:is([data-mk2-project-colors='off'], [data-mk2-status-bar='off']) :global(.hdr--wrapped) {
      --oc-task-indent: calc(var(--mk2-row-indent) - var(--mk2-pc) - var(--mk2-sb) - var(--oc-space-0-5));
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hss-head:not(.hss-head--empty)) {
      padding-left: calc(var(--mk2-head-indent) + var(--hd-step, 0px) - var(--mk2-pc));
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hds-sub) {
      padding-left: calc(var(--mk2-sub-indent) + var(--hd-step, 0px) - var(--mk2-pc));
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hd-pchev) {
      padding-left: calc(var(--mk2-chev-indent) - var(--mk2-pc));
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.tkm-state) {
      left: calc(var(--mk2-stripe-left) - var(--mk2-pc));
    }

    .mk2-frame :global(.hd-add .hdtl-key) {
      --oc-ibtn-size: 20px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
      flex: none;
      box-sizing: border-box;
      width: 20px;
      height: 20px;
      padding: 0;
      border: 1px solid var(--oc-orange);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-orange-tint);
      color: var(--oc-text-bright);
    }

    .mk2-frame :global(.hd-add .hdtl-key:hover:not(:disabled)) {
      border-color: var(--oc-orange-bright);
      background: var(--oc-orange-dim);
    }

    .mk2-frame :global(.hd-add .hdtl-key:disabled) {
      border-color: var(--oc-line-rule);
      background: none;
      color: var(--oc-text-dim);
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hd-block :is([data-huddle-item], [data-task-manager-level='status'], [data-task-manager-level='area'], [data-task-manager-level='sub'], [data-task-manager-group-empty]))::before {
      background: none;
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hd-group[data-task-manager-level='project']) {
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .mk2-frame[data-mk2-project-colors='off'] :global(.hd-group[data-task-manager-level='project'] .hd-pname) {
      color: var(--oc-text-secondary);
    }

    .mk2-frame[data-mk2-status-bar='off'] :global(.tkm-state) {
      display: none;
    }
  }
</style>

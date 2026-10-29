import { useFrameHeader } from '../../opscenter/shell/frame-header.svelte';
import { declareWidgetActions } from '../../opscenter/widgets/menu/declared-actions.svelte';


export const fakeActive = $state({ id: 'ses_1' });

interface ProbeProps {
  scope?: { sessionId: string; projectId: number | null } | null;
  page?: string;
}

export function ScopeProbe(anchor: Node, props: ProbeProps): void {
  const el = document.createElement('div');
  el.dataset['probe'] = '';
  anchor.parentNode?.insertBefore(el, anchor);
  $effect(() => {
    el.dataset['scope'] = props.scope ? `${props.scope.sessionId}:${props.scope.projectId}` : 'none';
    el.dataset['page'] = props.page ?? '';
  });
  $effect(() => () => el.remove());
}

export const fakeBadge = $state({ count: 3 as number | null, show: true });

export const fakeListing = $state({ data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/w' } }] });

export const fakePins = $state({
  sessions: { data: [] as unknown[] | null, status: 'ok' as string },
  asleep: { data: [] as unknown[] | null, status: 'ok' as string },
  recent: { data: { state: 'ok', sessions: [] as unknown[] } as { state: string; sessions: unknown[] } | null, status: 'ok' as string },
});

export const declaringLog = { live: 0, made: 0, runs: [] as number[] };

export const DECLARED_PROBE_ACTION = 'probe-act';

/* the widget menu */
export function DeclaringProbe(anchor: Node, _props: ProbeProps): void {
  const header = useFrameHeader();
  const copy = ++declaringLog.made;
  const el = document.createElement('div');
  el.dataset['declaringProbe'] = String(copy);
  anchor.parentNode?.insertBefore(el, anchor);
  $effect(() => {
    declaringLog.live += 1;
    return () => {
      declaringLog.live -= 1;
      el.remove();
    };
  });
  $effect(() => (header ? declareWidgetActions(header.hostId, 'probe', [{ id: DECLARED_PROBE_ACTION, label: 'probe act', run: () => declaringLog.runs.push(copy) }]) : undefined));
}

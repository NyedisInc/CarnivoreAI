import type { PlacementOptions } from '../../opscenter/widgets/placement-options';

export const probed: Record<string, { scope: string; options: string; writes: boolean; page: string }> = {};

interface ProbeProps {
  instance: string;
  scope?: { sessionId: string; projectId: number | null } | null;
  options?: PlacementOptions;
  onOption?: (option: string, value: boolean | number | string) => void;
  page?: string;
}

export function PlacementProbe(anchor: Node, props: ProbeProps): void {
  const el = document.createElement('div');
  el.dataset['probe'] = '';
  anchor.parentNode?.insertBefore(el, anchor);
  $effect(() => {
    probed[props.instance] = {
      scope: props.scope ? `${props.scope.sessionId}:${props.scope.projectId}` : 'none',
      options: JSON.stringify(props.options ?? {}),
      writes: typeof props.onOption === 'function',
      page: props.page ?? '',
    };
    el.dataset['scope'] = probed[props.instance]!.scope;
  });
  $effect(() => () => el.remove());
}

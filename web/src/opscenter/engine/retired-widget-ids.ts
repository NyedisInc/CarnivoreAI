
import declarations from '../../../../src/data/widgets.json';

export const RETIRED_WIDGET_SUCCESSOR: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries((declarations as { replaced?: Record<string, string[]> }).replaced ?? {})
    .filter(([, successors]) => successors.length === 1)
    .map(([retired, successors]) => [retired, successors[0] as string]),
);

export function currentWidgetId(id: string): string {
  return RETIRED_WIDGET_SUCCESSOR[id] ?? id;
}

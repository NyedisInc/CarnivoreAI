import type { ApprovalItem } from '../../../lib/approvals/approvals-model';
import type { TaskManagerGroup } from '../../../cplugs/huddle/huddle-model';
import type { AppAlert } from '../../../lib/app-alerts/alerts-model';
import type { RunRow } from '../developer/model';
import { alertRows, approvalRows, failedAutomationRows, taskManagerRows, type AttentionRow, type AttentionTarget, type Translate } from '../../../lib/attention-kinds/rows';
import type { PlacementOptions } from '../../widgets/placement-options';
import { copyListsKind } from './sources';

export type QuestionRow = AttentionRow;
export type QuestionTarget = AttentionTarget;

export function filterRows(rows: readonly QuestionRow[], options: PlacementOptions | undefined): QuestionRow[] {
  return rows.filter((row) => copyListsKind(options, row.kindId));
}

export function orderQuestions(rows: readonly QuestionRow[], options?: PlacementOptions): QuestionRow[] {
  return filterRows(rows, options)
    .map((row, index) => ({ row, index }))
    .sort((a, b) => (a.row.atMs ?? Infinity) - (b.row.atMs ?? Infinity) || a.index - b.index)
    .map((entry) => entry.row);
}

export function mergeQuestions(
  approvals: readonly ApprovalItem[],
  groups: readonly TaskManagerGroup[] | null,
  alerts: readonly AppAlert[] = [],
  translate: Translate = (key) => key,
  options?: PlacementOptions,
  runs: readonly RunRow[] = [],
): QuestionRow[] {
  return orderQuestions([...approvalRows(approvals), ...taskManagerRows(groups), ...alertRows(alerts, translate), ...failedAutomationRows(runs)], options);
}

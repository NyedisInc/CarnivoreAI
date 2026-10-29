import { attentionRows, attentionUnread } from '../../../lib/attention-kinds/read.svelte';
import type { PlacementOptions } from '../../widgets/placement-options';
import { orderQuestions, type QuestionRow } from './model';

export function questionRows(options?: PlacementOptions): QuestionRow[] {
  return orderQuestions(attentionRows(), options);
}

export function questionCount(options?: PlacementOptions): number | null {
  return attentionUnread() ? null : questionRows(options).length;
}

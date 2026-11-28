import { describe, expect, test } from 'vitest';
import { t } from '../../lib/i18n/index.svelte';
import { REGISTRY } from '../cells/registry';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { META } from './meta';
import { HIDDEN_BY_DEFAULT, offSurfaceIds, resetLayout } from './model';
import { validate } from './persist';
import { widgetIdOfTab } from './widget-tabs';
import type { LayoutPage } from './types';

const SUCCESSOR: Record<string, string> = {
  'task-manager': 'task-manager-mk2',
  'task-list': 'task-manager-mk2',
  'task-manager-all': 'task-manager-mk2-all',
};

function savedHolding(page: LayoutPage, retired: string): { rows: Array<{ slots: Array<{ id: string; fr: number }> }>; hidden: string[] } {
  const stored = JSON.parse(JSON.stringify(resetLayout(META, page))) as {
    rows: Array<{ slots: Array<{ id: string; fr: number }> }>;
    hidden: string[];
  };
  const slot = stored.rows[0]!.slots[0]!;
  stored.hidden = [...stored.hidden.filter((id) => id !== retired), slot.id];
  slot.id = retired;
  return stored;
}

describe('one task manager', () => {
  for (const [retired, successor] of Object.entries(SUCCESSOR)) {
    for (const page of ['home', 'terminal', 'warroom'] as const) {
      test(`${page}: a saved ${retired} in a row slot reads back as ${successor} in that slot`, () => {
        const stored = savedHolding(page, retired);
        const was = stored.rows[0]!.slots[0]!.fr;
        stored.hidden = stored.hidden.filter((id) => id !== successor);
        const checked = validate(stored, META, page);
        expect(checked.refusal).toBeNull();
        expect(checked.migrated).toBe(true);
        const slot = checked.layout!.rows[0]!.slots[0]!;
        expect(slot.id).toBe(successor);
        expect(slot.fr).toBeCloseTo(was, 10);
      });

      test(`${page}: a saved ${retired} in the hidden list reads back as ${successor} hidden`, () => {
        const stored = JSON.parse(JSON.stringify(resetLayout(META, page))) as { hidden: string[] };
        stored.hidden = [...stored.hidden.filter((id) => id !== successor && id !== retired), retired];
        const checked = validate(stored, META, page);
        expect(checked.refusal).toBeNull();
        expect(offSurfaceIds(checked.layout!)).toContain(successor);
        expect(offSurfaceIds(checked.layout!)).not.toContain(retired);
      });
    }
  }

  test('the retired cells are gone from the registry, the meta, the manifests and the hidden-by-default list', () => {
    for (const retired of Object.keys(SUCCESSOR)) {
      expect(retired in REGISTRY).toBe(false);
      expect(retired in META).toBe(false);
      expect(`core.${retired}` in CORE_MANIFESTS).toBe(false);
      expect(HIDDEN_BY_DEFAULT).not.toContain(retired);
    }
  });

  test('the picker lists Mark II and none of the retired three', () => {
    const picker = offSurfaceIds(resetLayout(META, 'home'));
    for (const retired of Object.keys(SUCCESSOR)) expect(picker).not.toContain(retired);
    expect(picker).toContain('task-manager-mk2');
    expect(picker).toContain('task-manager-mk2-all');
  });

  test('Mark II is titled "task manager" and "all task managers"', () => {
    expect(t(META['task-manager-mk2'].titleKey)).toBe('task manager');
    expect(t(META['task-manager-mk2-all'].titleKey)).toBe('all task managers');
  });

  test('a widget tab saved for a retired widget opens its Mark II successor, never a blank body', () => {
    expect(widgetIdOfTab('widget:core.task-manager')).toBe('core.task-manager-mk2');
    expect(widgetIdOfTab('widget:core.task-list')).toBe('core.task-manager-mk2');
    expect(widgetIdOfTab('widget:core.task-manager-all')).toBe('core.task-manager-mk2-all');
    expect(widgetIdOfTab('widget:core.tasks')).toBe('core.tasks');
  });
});

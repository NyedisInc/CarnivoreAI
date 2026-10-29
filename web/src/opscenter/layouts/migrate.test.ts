/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const listing = vi.hoisted(() => ({ data: [] as unknown[], status: 'ok' as string, refresh: vi.fn(async () => undefined) }));
vi.mock('../api', () => ({ sessions: listing }));

const created = vi.hoisted(() => vi.fn());
vi.mock('./api', async (actual) => {
  const real = await actual<typeof import('./api')>();
  return { ...real, createLayout: created, listLayouts: vi.fn() };
});

const queued = vi.hoisted(() => vi.fn());
const prefsApi = vi.hoisted(() => ({
  HYDRATED: 'hydrated',
  status: () => 'hydrated',
  committedValue: vi.fn(),
}));
vi.mock('../engine/arrangement-sync.svelte', () => ({
  preferencesApi: () => prefsApi,
  queueEntry: queued,
}));

import { PRIMARY_SLOT } from '../engine/model';
import type { Layout } from '../engine/types';
import { ApiError } from '../api/auth.svelte';
import { listLayouts } from './api';
import { epochOf, resetLayoutMigration, runLayoutMigration, stripSplit, tmuxNameOf } from './migrate';

function grid(...ids: string[]): Layout {
  return {
    v: 6,
    rows: [{ id: 'r1', kind: 'flex', size: 1, slots: ids.map((id) => ({ id: id as never, fr: 1 / ids.length })) }],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  };
}

const bootDone = { AppBootComplete: { isComplete: () => true } } as unknown as Window;

function row(
  name: string, rowId: number, id = `ses_${rowId}`, epoch: number | null = null,
): Record<string, unknown> {
  return {
    session: { id, tmux_created_epoch: epoch },
    session_row_id: rowId,
    tmux_session: name,
    label: null,
  };
}

beforeEach(() => {
  resetLayoutMigration();
  created.mockReset();
  queued.mockReset();
  listing.data = [];
  listing.status = 'ok';
  listing.refresh.mockClear();
  prefsApi.committedValue.mockReset();
  vi.mocked(listLayouts).mockReset();
  vi.mocked(listLayouts).mockResolvedValue({ status: 'ok', layouts: [], detail: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('tmuxNameOf', () => {
  test('strips a trailing numeric epoch', () => {
    expect(tmuxNameOf('cloude_api:1758000000')).toBe('cloude_api');
  });

  test('a bare name with no epoch is unchanged', () => {
    expect(tmuxNameOf('cloude_api')).toBe('cloude_api');
  });
});

describe('epochOf', () => {
  test('reads a trailing numeric epoch', () => {
    expect(epochOf('cloude_api:1758000000')).toBe(1758000000);
  });

  test('a bare name with no epoch is null', () => {
    expect(epochOf('cloude_api')).toBeNull();
  });
});

describe('stripSplit', () => {
  test('removes every visible terminal component but the anchor\'s own, keeping its own tabs', () => {
    const layout = grid(PRIMARY_SLOT, 'terminal:row:2');
    const groups = { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:9'] }, 'terminal:row:2': { tabs: ['terminal:row:2'] } };
    const stripped = stripSplit(layout, groups);
    expect(stripped.groups).toEqual({ [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:row:9'] } });
    expect(stripped.layout?.rows.length).toBe(1);
    expect(stripped.layout?.rows[0]?.slots.map((slot) => slot.id)).toEqual([PRIMARY_SLOT]);
  });
});

describe('runLayoutMigration', () => {
  test('a split grid migrates: created with a source_key, then the split is stripped', async () => {
    listing.data = [row('cloude_api', 1), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, 'terminal:ses_2': { tabs: ['terminal:ses_2'] } },
        },
      },
    });
    created.mockResolvedValue({ layout: { layout_uuid: 'L1' }, created: true, deleted: false, survivor: null });

    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(1);
    const [name, shape, sourceKey] = created.mock.calls[0]!;
    expect(sourceKey).toBe('terminal_layouts:cloude_api');
    expect(typeof name).toBe('string');
    expect(shape.groups[PRIMARY_SLOT].tabs).toContain('terminal:row:1');
    expect(queued).toHaveBeenCalledTimes(1);
    const [key, entry] = queued.mock.calls[0]!;
    expect(key).toBe('cloude_api');
    expect(entry.groups).toEqual({ [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] } });
  });

  test('a tab-only grid (one visible terminal, several tabs) is never touched', async () => {
    listing.data = [row('cloude_api', 1), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT),
          groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, 'terminal:ses_2'] } },
        },
      },
    });

    await runLayoutMigration(bootDone);

    expect(created).not.toHaveBeenCalled();
    expect(queued).not.toHaveBeenCalled();
  });

  test('strip only after a 2xx: a refused create leaves the entry alone', async () => {
    listing.data = [row('cloude_api', 1), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: {},
        },
      },
    });
    created.mockRejectedValue(new ApiError('down', 503, null, { detail: { code: 'layouts_unavailable', detail: 'down' } }));

    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(1);
    expect(queued).not.toHaveBeenCalled();
  });

  test('a name collision is uniquified and retried before giving up', async () => {
    listing.data = [row('cloude_api', 1), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: {},
        },
      },
    });
    created
      .mockRejectedValueOnce(new ApiError('taken', 409, null, { detail: { code: 'layout_name_taken', detail: 'taken' } }))
      .mockResolvedValueOnce({ layout: { layout_uuid: 'L1' }, created: true, deleted: false, survivor: null });

    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(2);
    const firstName = created.mock.calls[0]![0];
    const secondName = created.mock.calls[1]![0];
    expect(secondName).not.toBe(firstName);
    expect(queued).toHaveBeenCalledTimes(1);
  });

  test('an unresolved anchor (its own session not live yet) is left for a later boot', async () => {
    listing.data = [row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: {},
        },
      },
    });

    await runLayoutMigration(bootDone);

    expect(created).not.toHaveBeenCalled();
    expect(queued).not.toHaveBeenCalled();
  });

  test('issue #907: a reused tmux name at a DIFFERENT epoch is never anchored to', async () => {
    listing.data = [row('cloude_api', 1, 'ses_1', 1758999999), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        'cloude_api:1758000000': {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: {},
        },
      },
    });

    await runLayoutMigration(bootDone);

    expect(created).not.toHaveBeenCalled();
    expect(queued).not.toHaveBeenCalled();
  });

  test('issue #907: a key epoch that matches the live row anchors normally', async () => {
    listing.data = [row('cloude_api', 1, 'ses_1', 1758000000), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        'cloude_api:1758000000': {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, 'terminal:ses_2': { tabs: ['terminal:ses_2'] } },
        },
      },
    });
    created.mockResolvedValue({ layout: { layout_uuid: 'L1' }, created: true, deleted: false, survivor: null });

    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(1);
    const [, shape, sourceKey] = created.mock.calls[0]!;
    expect(sourceKey).toBe('terminal_layouts:cloude_api:1758000000');
    expect(shape.groups[PRIMARY_SLOT].tabs).toContain('terminal:row:1');
    expect(queued).toHaveBeenCalledTimes(1);
  });

  test('issue #907: no epoch on the key (pre-epoch data) falls back to the name alone', async () => {
    listing.data = [row('cloude_api', 1, 'ses_1', 1758000000), row('cloude_web', 2)];
    prefsApi.committedValue.mockReturnValue({
      v: 1,
      sessions: {
        cloude_api: {
          layout: grid(PRIMARY_SLOT, 'terminal:ses_2'),
          groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, 'terminal:ses_2': { tabs: ['terminal:ses_2'] } },
        },
      },
    });
    created.mockResolvedValue({ layout: { layout_uuid: 'L1' }, created: true, deleted: false, survivor: null });

    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(1);
    expect(queued).toHaveBeenCalledTimes(1);
  });

  test('idempotent rerun: the same entry computes the same source_key every boot', async () => {
    listing.data = [row('cloude_api', 1), row('cloude_web', 2)];
    const arrangement = {
      v: 1,
      sessions: { cloude_api: { layout: grid(PRIMARY_SLOT, 'terminal:ses_2'), groups: {} } },
    };
    prefsApi.committedValue.mockReturnValue(arrangement);
    created.mockResolvedValue({ layout: { layout_uuid: 'L1' }, created: false, deleted: false, survivor: null });

    await runLayoutMigration(bootDone);
    resetLayoutMigration();
    await runLayoutMigration(bootDone);

    expect(created).toHaveBeenCalledTimes(2);
    expect(created.mock.calls[0]![2]).toBe(created.mock.calls[1]![2]);
  });
});

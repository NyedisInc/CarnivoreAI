import { describe, expect, it } from 'vitest';
import { computeTracks, GUTTER } from './tracks';
import { boundaryHandles } from './row-handles';
import { resizeRows } from './model';
import { ROW_MIN } from './floors';
import { foldSpanOnlyRows } from './compact';
import { repairSpans, spanOf } from './spans';
import type { Layout } from './types';

const SHAPE: any = {
 "v": 6,
 "rows": [
  {
   "id": "r14",
   "kind": "flex",
   "size": 0.7439333771587187,
   "slots": [
    {
     "id": "terminal:@primary",
     "fr": 0.5,
     "span": 8
    },
    {
     "id": "terminal:row:311",
     "fr": 0.5,
     "span": 7
    }
   ]
  },
  {
   "id": "r15",
   "kind": "flex",
   "size": 0.04108309990662932,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r20",
   "kind": "flex",
   "size": 0.13994991803910584,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r19",
   "kind": "flex",
   "size": 0.004915102770330653,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r18",
   "kind": "flex",
   "size": 0.009830205540661306,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r17",
   "kind": "flex",
   "size": 0.01966041108132261,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r16",
   "kind": "flex",
   "size": 0.020313942751615882,
   "slots": [],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    },
    {
     "of": "terminal:row:311",
     "at": 0
    }
   ]
  },
  {
   "id": "r21",
   "kind": "flex",
   "size": 0.020313942751615882,
   "slots": [
    {
     "id": "terminal:row:192",
     "fr": 1
    }
   ],
   "reserved": [
    {
     "of": "terminal:@primary",
     "at": 0
    }
   ]
  }
 ],
 "hidden": [
  "files",
  "notes"
 ],
 "heroCollapsed": false,
 "collapsed": []
};
const W = 1530;
const H = 1150;
const draw = (l: Layout) => computeTracks({ rows: l.rows, width: W, height: H, gutter: GUTTER } as any);
const raw = repairSpans(SHAPE as Layout);
const healed = foldSpanOnlyRows(raw);

describe('freeform seam resize (#2269)', () => {
  it('grows an undersized cell from the raw shape', () => {
    const t = draw(raw);
    const next = resizeRows(raw, 'r16', -300, t.flexSpace);
    expect(next).not.toBe(raw);
    const rows = draw(next).rows;
    expect(rows[rows.length - 1]!.height).toBeGreaterThanOrEqual(300);
  });

  it('folds the slot-less rows away', () => {
    expect(healed.rows.map((r) => r.id)).toEqual(['r14', 'r21']);
    expect(spanOf(healed.rows[0]!.slots[0]!)).toBe(2);
    expect(healed.rows.reduce((sum, r) => sum + r.size, 0)).toBeCloseTo(1, 9);
    expect(foldSpanOnlyRows(healed)).toBe(healed);
  });

  it('follows the pointer 1:1 on the healed shape', () => {
    const t = draw(healed);
    expect(boundaryHandles(t, 0, W, GUTTER)).toEqual([[771, 759]]);
    const before = t.rows[1]!.height;
    for (const dy of [-1, -37, -250, -400]) {
      const rows = draw(resizeRows(healed, 'r14', dy, t.flexSpace)).rows;
      expect(Math.abs(rows[1]!.height - (before - dy))).toBeLessThanOrEqual(1);
    }
  });

  it('floors bind only the rows giving space', () => {
    const t = draw(healed);
    const squeezed = draw(resizeRows(healed, 'r14', -5000, t.flexSpace)).rows;
    expect(squeezed[0]!.height).toBeCloseTo(ROW_MIN, 3);
    expect(resizeRows(healed, 'r14', 50, t.flexSpace)).toBe(healed);
  });
});

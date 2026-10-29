import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { REPORT_CAP_BYTES, REPORT_NEAR_CAP_BYTES } from './report-cap';

const read = (p: string): string => readFileSync(`${process.cwd()}/${p}`, 'utf8');

test('the client cap is the server cap', () => {
  expect(read('../src/core/automations/models.py')).toMatch(/^REPORT_CAP_BYTES = 1 << 20$/m);
  expect(REPORT_CAP_BYTES).toBe(1 << 20);
  expect(REPORT_NEAR_CAP_BYTES).toBe(524288);
});

test.each(['src/lib/automations/logic/report-rules.ts', 'src/lib/automations/report/RunHeader.svelte', 'src/lib/automations/feed/feed-model.ts'])(
  '%s names the threshold instead of repeating 524288',
  (file) => {
    expect(read(file).replace(/\(with "of 1 MB cap" at 524288 bytes\)/, '')).not.toMatch(/\b524288\b/);
  },
);

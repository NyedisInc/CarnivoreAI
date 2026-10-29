/*  svelte-check */
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const BASELINE_PATH = fileURLToPath(new URL('./baseline.json', import.meta.url));

/*  svelte-check */
export function countErrors(output) {
  const rows = output.split('\n');
  return {
    errors: rows.filter((row) => / ERROR "/.test(row)).length,
    completed: rows.some((row) => / COMPLETED \d+ FILES /.test(row)),
  };
}

export function judge(measured, baseline) {
  if (!measured.completed) return { code: 2, message: 'svelte-check did not finish, so the count is unknown.' };
  if (measured.errors > baseline) {
    return { code: 1, message: `${measured.errors} type errors, ${measured.errors - baseline} above the baseline of ${baseline}. Fix the new ones; never raise the baseline.` };
  }
  if (measured.errors < baseline) {
    return { code: 0, message: `${measured.errors} type errors, under the baseline of ${baseline}: lower "errors" in scripts/type-check-ratchet/baseline.json to ${measured.errors}.` };
  }
  return { code: 0, message: `${measured.errors} type errors, equal to the baseline.` };
}

/*  svelte-check */
function main() {
  const baseline = JSON.parse(readFileSync(BASELINE_PATH, 'utf8')).errors;
  const run = spawnSync('npx', ['svelte-check', '--tsconfig', './tsconfig.json', '--output', 'machine'], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
  const verdict = judge(countErrors(`${run.stdout ?? ''}\n${run.stderr ?? ''}`), baseline);
  console.log(verdict.message);
  process.exit(verdict.code);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();

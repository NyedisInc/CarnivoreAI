/* there is nothing */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect } from 'vitest';

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '__goldens__');

export const UPDATING = typeof process !== 'undefined' && process.env.SIDEBAR_GOLDENS === 'update';

const cache = new Map<string, Record<string, unknown>>();

const perTest = new Map<string, number>();

function load(suite: string): Record<string, unknown> {
    let data = cache.get(suite);
    if (data) return data;
    const file = path.join(DIR, `${suite}.json`);
    data = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) as Record<string, unknown> : {};
    cache.set(suite, data);
    return data;
}

export function suiteOfTest(): string {
    const file = expect.getState().testPath || 'unknown';
    return path.basename(file).replace(/\.ts$/, '');
}

function nextSlot(): string {
    const name = expect.getState().currentTestName || 'unnamed';
    const n = perTest.get(name) || 0;
    perTest.set(name, n + 1);
    return `${name} #${n}`;
}

export function legacyAnswer<T>(suite: string, current: T): T {
    const slot = nextSlot();
    const data = load(suite);
    if (UPDATING) {
        data[slot] = current as unknown;
        fs.mkdirSync(DIR, { recursive: true });
        fs.writeFileSync(path.join(DIR, `${suite}.json`), `${JSON.stringify(data, null, 1)}\n`);
        return current;
    }
    if (!(slot in data)) throw new Error(`no legacy recording for "${slot}" in __goldens__/${suite}.json`);
    return data[slot] as T;
}

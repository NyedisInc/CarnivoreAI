import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { knownListRatchet, stripComments, walkSources } from '../test-support/source-scan';

/** `client/js`, from web/src/lib. */
const LEGACY = path.resolve(__dirname, '../../../client/js');

const FIXTURE = path.resolve(__dirname, '../../../tests/fixtures/design_legacy_known.json');

type JsControls = Record<string, Record<string, number>>;

function loadKnown(): string[] {
    const doc: unknown = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
    const rows = (doc as { sections?: { js_controls?: JsControls } }).sections?.js_controls;
    if (!rows || Object.keys(rows).length === 0) throw new Error(`${FIXTURE} has no js_controls rows`);
    return Object.entries(rows)
        .filter(([, kinds]) => (kinds['dom-write'] ?? 0) > 0)
        .map(([rel]) => rel.replace(/^client\/js\//, ''));
}

export const LEGACY_DOM_KNOWN: readonly string[] = loadKnown();

const DOM_WRITE = /\b(createElement|createElementNS|createDocumentFragment|insertAdjacentHTML)\s*\(|\b(innerHTML|outerHTML)\s*\+?=(?!=)/;

export function writesDom(text: string): boolean {
    return DOM_WRITE.test(stripComments(text));
}

describe('client/js gets no new DOM-writing file', () => {
    const writers = walkSources(LEGACY, /\.m?js$/).filter((file) => writesDom(fs.readFileSync(path.join(LEGACY, file), 'utf8')));

    it('looked at the legacy tree and read the fixture (a scan of nothing is not a pass)', () => {
        expect(writers.length).toBeGreaterThan(20);
        expect(LEGACY_DOM_KNOWN.length).toBeGreaterThan(20);
    });

    it('has no DOM-writing file outside LEGACY_DOM_KNOWN (build new UI in web/)', () => {
        expect(knownListRatchet(writers, LEGACY_DOM_KNOWN).unlisted).toEqual([]);
    });

    it('keeps every LEGACY_DOM_KNOWN row true (a ported or cleaned file leaves the list)', () => {
        expect(knownListRatchet(writers, LEGACY_DOM_KNOWN).stale).toEqual([]);
    });

    it('goes red on a fixture (negative control)', () => {
        expect(writesDom("const d = document.createElement('div');")).toBe(true);
        expect(writesDom('el.innerHTML = html;')).toBe(true);
        expect(writesDom('el.innerHTML == html; // innerHTML = x')).toBe(false);
        expect(writesDom('/* createElement(x) */ const a = 1;')).toBe(false);
    });
});

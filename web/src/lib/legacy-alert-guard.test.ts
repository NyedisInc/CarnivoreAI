import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { knownListRatchet, stripComments, walkSources } from '../test-support/source-scan';

/** `client/js`, from web/src/lib. */
const LEGACY = path.resolve(__dirname, '../../../client/js');

export const ALERT_KNOWN: readonly string[] = [];

export function callsAlert(text: string): boolean {
    return /(^|[^.\w])alert\(/m.test(stripComments(text));
}

describe('client/js raises no new browser alert()', () => {
    const callers = walkSources(LEGACY, /\.m?js$/).filter((file) => callsAlert(fs.readFileSync(path.join(LEGACY, file), 'utf8')));

    it('looked at the legacy tree (a scan of nothing is not a pass)', () => {
        expect(walkSources(LEGACY, /\.m?js$/).length).toBeGreaterThan(100);
    });

    it('has no alert() caller outside ALERT_KNOWN (use WriteFailureNotice.reportKey)', () => {
        expect(knownListRatchet(callers, ALERT_KNOWN).unlisted).toEqual([]);
    });

    it('keeps every ALERT_KNOWN row true (a fixed file leaves the list)', () => {
        expect(knownListRatchet(callers, ALERT_KNOWN).stale).toEqual([]);
    });

    it('goes red on a fixture (negative control)', () => {
        expect(callsAlert("alert('could not restart');")).toBe(true);
        expect(callsAlert('// alert(x)\nwindow.notice.alert(x); const malert = 1;')).toBe(false);
    });
});

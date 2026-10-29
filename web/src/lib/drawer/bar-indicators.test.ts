/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, it } from 'vitest';
import * as Bar from './bar';
import { versionFooterStub } from './test-support';
import { cplugBarIndicators } from '../../cplugs/host/readers';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { beastStatus } from '../beast-mode/control.svelte';
import type { CplugManifest, CplugWeb } from '../../cplugs/sdk';

const MANIFEST = { id: 'fake', default_enabled: true } as unknown as CplugManifest;

function fakePlugin(state: { on: boolean; runs: number }): CplugWeb {
    return {
        id: 'fake', manifest: MANIFEST,
        barIndicators: [{ id: 'lit', icon: 'bolt', visible: () => state.on, label: () => 'fake is on', run: () => { state.runs += 1; } }],
    };
}

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div>';
    Bar.reset();
    (window as unknown as Record<string, unknown>).CloudeWeb = { masterAllEnabled: () => true, setMasterAll: () => undefined };
    (window as unknown as Record<string, unknown>).VersionFooter = versionFooterStub('1.2.3');
});

afterEach(() => {
    beastStatus.data = null;
    cplugEnablement.enabled = {};
    delete (window as unknown as Record<string, unknown>).CloudeWeb;
    delete (window as unknown as Record<string, unknown>).VersionFooter;
});

describe('plugin bar indicators', () => {
    it('the reader shows an indicator only while its plugin is on and it says so', () => {
        const state = { on: false, runs: 0 };
        const list = [fakePlugin(state)];
        assert.deepEqual(cplugBarIndicators(list), [], 'not visible: nothing');
        state.on = true;
        assert.deepEqual(cplugBarIndicators(list).map((i) => i.action), ['cplug:fake.lit']);
        cplugEnablement.enabled = { fake: false };
        assert.deepEqual(cplugBarIndicators(list), [], 'plugin off: nothing, whatever the indicator says');
    });

    it('the beast bolt is drawn right of the crown, before the version, only while armed, and its words say until when', () => {
        Bar.paint();
        const slot = document.getElementById('session-sidebar-bar-slot')!;
        assert.equal(slot.querySelector('[data-bar-indicator="beast.armed"]'), null, 'disarmed: no bolt');
        beastStatus.data = { enabled: true, prompts: true, since: null, until: null, pending_count: 0 };
        Bar.paint();
        const right = slot.querySelector('.session-sidebar-bar__version')!;
        const order = [...right.children].map((el) => el.id || el.getAttribute('data-bar-indicator') || el.getAttribute('data-bar-action') || el.className);
        assert.deepEqual(order, ['sidebarMasterAllBtn', 'beast.armed', 'version-footer']);
        const bolt = right.querySelector('[data-bar-indicator="beast.armed"]')!;
        assert.equal(bolt.getAttribute('data-bar-action'), 'beast:armed');
        assert.equal(bolt.getAttribute('aria-label'), 'beast mode is on, answering session prompts too');
        assert.equal(bolt.getAttribute('data-size'), 'icon', 'the base icon button');
        assert.equal(slot.querySelector('[data-bar-action="beast"]'), null, 'the old arm bolt left of the chip is gone');
    });

    it('disarmed with a beast off auto-approve box ticked, the same bolt shows quiet and says so (#1792 finding 2)', () => {
        const slot = document.getElementById('session-sidebar-bar-slot')!;
        beastStatus.data = { enabled: false, since: null, pending_count: 0, auto_off_rows: [] };
        Bar.paint();
        assert.equal(slot.querySelector('[data-bar-indicator="beast.armed"]'), null, 'nothing ticked: no bolt');
        beastStatus.data = { enabled: false, since: null, pending_count: 0, auto_off_rows: ['agent_writes'] };
        Bar.paint();
        const bolt = slot.querySelector('[data-bar-indicator="beast.armed"]')!;
        assert.ok(bolt.hasAttribute('data-bar-indicator-quiet'));
        assert.match(bolt.getAttribute('title') ?? '', /auto approving with beast off/);
        beastStatus.data = { enabled: true, since: null, pending_count: 0, auto_off_rows: ['agent_writes'] };
        Bar.paint();
        assert.ok(!slot.querySelector('[data-bar-indicator="beast.armed"]')!.hasAttribute('data-bar-indicator-quiet'),
            'armed: the lit bolt');
    });

    it('the armed bolt is painted in the danger token, the quiet one is not, and the bolt sits closer to the crown', () => {
        const css = readFileSync(resolve(process.cwd(), '../client/css/session-sidebar.css'), 'utf8');
        assert.match(css, /\.session-sidebar-bar__version > \[data-bar-indicator\]:not\(\[data-bar-indicator-quiet\]\) \{\s*color: var\(--oc-coral\);/,
            'armed: coral, stronger than the bar button rule');
        assert.match(css, /\.session-sidebar-bar__version > \[data-bar-indicator\] \{\s*margin-left: -4px;/, 'closer to the crown');
        beastStatus.data = { enabled: false, since: null, pending_count: 0, auto_off_rows: ['agent_writes'] };
        Bar.paint();
        const bolt = document.querySelector('[data-bar-indicator="beast.armed"]')!;
        assert.ok(bolt.hasAttribute('data-bar-indicator-quiet'), 'quiet bolt carries the marker the coral rule excludes');
    });

    it('a click on an indicator runs its plugin handler and nothing else', () => {
        const state = { on: true, runs: 0 };
        const list = [fakePlugin(state)];
        const [item] = cplugBarIndicators(list);
        item!.run(null);
        assert.equal(state.runs, 1);
        Bar.run('cplug:nobody.nothing', null);
    });
});

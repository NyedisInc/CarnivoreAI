/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, describe, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import { STORAGE_KEY } from '../drawer/store';
import * as ListingState from '../drawer/listing-state';

function row(over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'cloude_a', created_by_cloude: true, created_at_epoch: 1000, is_active: true,
        is_this_tab: false, is_pinned: false, status: 'working', unread: false, session_id: null,
        agent_family: null, agent_family_source: 'unknown', pinned_theme: null, ...over,
    };
}

beforeAll(() => {
    loadLegacyDrawer();
});

beforeEach(() => {
    resetDrawer();
    Density.setMode('cozy');
});

describe('a failed listing is not an empty list', () => {
    it('zero rows from a FAILED listing renders CANNOT DETERMINE, never the empty state', () => {
        const html = drawList([], { _listing: { ok: false, reason: 'tmux_missing', detail: 'tmux is gone' } });
        assert.ok(html.includes('CANNOT DETERMINE'), 'the failure must be stated');
        assert.ok(html.includes('tmux is gone'), 'and it must say what failed');
        assert.ok(html.includes('data-listing-reason="tmux_missing"'), 'machine-readable too');
        assert.ok(!html.includes('session-sidebar-empty'),
            'the confident empty state is the false green this exists to remove');
        assert.ok(!html.includes('data-session-action'),
            'a block about sessions we cannot confirm must offer no actions');
    });

    it('zero rows from a listing that ANSWERED still renders the honest empty state', () => {
        const html = drawList([], { _listing: { ok: true } });
        assert.ok(html.includes('no other agents'));
        assert.ok(!html.includes('CANNOT DETERMINE'));
    });

    it('the reason and detail come from the SERVER verdict, not a browser guess', () => {
        const S = ListingState;
        const err = Object.assign(new Error('boom'),
            { detail: { listing_reason: 'tmux_missing', listing_detail: 'tmux is not installed' } });
        assert.equal(S.reasonFromError(err, 503), 'tmux_missing');
        assert.equal(S.detailFromError(err, 503), 'tmux is not installed');
        assert.equal(S.reasonFromError(new Error(''), 0), 'network_error');
        assert.ok(S.detailFromError(new Error(''), 0).length > 0);
        assert.equal(S.attentionHtml({ ok: true }), '', 'a healthy listing draws nothing');
    });
});

describe('the arrangement notice is really rendered', () => {
    it('an unreadable arrangement renders a notice ALONGSIDE the fallback rows', () => {
        localStorage.setItem(STORAGE_KEY, '{not json');
        Store.load();
        const html = drawList([row({ name: 'a' })]);
        assert.ok(html.includes('CANNOT LOAD your saved order'));
        assert.ok(html.includes('stored value is not valid JSON'), 'it must say why');
        assert.ok(html.includes('data-name="a"'), 'and the list still works');
    });

    it('a healthy arrangement renders NO notice - a check that never clears is furniture', () => {
        Store.load();
        assert.ok(!drawList([row()]).includes('CANNOT LOAD'));
        Store.save(['cloude_a'], ['cloude_a']);
        assert.equal(Store.current().status, 'ok');
        assert.ok(!drawList([row()]).includes('CANNOT LOAD'));
    });
});

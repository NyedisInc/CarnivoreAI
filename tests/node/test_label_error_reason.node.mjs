import assert from 'node:assert/strict';
import { reasonOf, SERVER_UNREACHABLE_KEY } from '../../client/js/labels/error-reason.js';
import { attributionFailedDetail, projectsLoadFailed } from '../../client/js/labels/session-listing.js';

const t = (key, params) => (params ? `${key}:${params.reason}` : `<${key}>`);

assert.equal(reasonOf(new Error('timeout'), t), 'timeout');
assert.equal(reasonOf('plain', t), 'plain');
assert.equal(reasonOf(new Error(''), t), `<${SERVER_UNREACHABLE_KEY}>`, 'an empty message must not read "Error"');
assert.equal(reasonOf(new Error('   '), t), `<${SERVER_UNREACHABLE_KEY}>`);
assert.equal(reasonOf(undefined, t), `<${SERVER_UNREACHABLE_KEY}>`);
assert.equal(reasonOf(null, t), `<${SERVER_UNREACHABLE_KEY}>`);
assert.equal(reasonOf({ message: 'x' }, t), 'x');
assert.equal(attributionFailedDetail(new Error(''), t), `<${SERVER_UNREACHABLE_KEY}>`);
assert.equal(projectsLoadFailed(new Error('boom'), t), 'project.list.load_failed:boom');
console.log('ALL PASS');

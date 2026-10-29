// the home screen
// It is NOT a browser and computes NO layout.
// Not a test file: the suites are `tests/*.node.mjs`, this is `.mjs`.


import fs from 'node:fs';
import path from 'node:path';

import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.join(__dirname, '..');
export const STYLES = fs.readFileSync(path.join(ROOT, 'client', 'css', 'styles.css'), 'utf8');
export const INDEX = fs.readFileSync(path.join(ROOT, 'client', 'index.html'), 'utf8');

const counts = { passes: 0, failures: 0 };

export function results() { return counts; }

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => (void|Promise<void>)} fn  Body; throwing marks it failed.
 * @returns {Promise<void>}
 */
export async function test(name, fn) {
    try {
        await fn();
        counts.passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        counts.failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

export function ruleBody(css, selector) {
    const idx = css.indexOf(`\n${selector} {`);
    assert.ok(idx !== -1, `expected a rule for ${selector}`);
    const open = css.indexOf('{', idx);
    const close = css.indexOf('}', open);
    return css.slice(open + 1, close);
}

export function el(tag, opts = {}) {
    const classes = tag.split(/\s+/).filter(Boolean);
    const node = {
        id: opts.id || '',
        innerHTML: '',
        textContent: '',
        style: {},
        dataset: opts.dataset || {},
        parent: null,
        children: opts.children || [],
        _attrs: Object.assign({}, opts.attrs),
        classes,
        setAttribute(n, v) { this._attrs[n] = String(v); },
        getAttribute(n) {
            return Object.prototype.hasOwnProperty.call(this._attrs, n) ? this._attrs[n] : null;
        },
        hasAttribute(n) { return Object.prototype.hasOwnProperty.call(this._attrs, n); },
        addEventListener() {},
        appendChild(child) { this.children.push(child); child.parent = this; return child; },
        removeChild(child) { this.children = this.children.filter((c) => c !== child); },
        scrollIntoView() {},
        classList: {
            add: (c) => { if (!classes.includes(c)) classes.push(c); },
            remove: (c) => { const i = classes.indexOf(c); if (i >= 0) classes.splice(i, 1); },
            toggle() {},
            contains: (c) => classes.includes(c),
        },
        closest(sel) {
            const want = sel.replace(/^\./, '');
            let cur = this;
            while (cur) {
                if (cur.classes && cur.classes.includes(want)) return cur;
                cur = cur.parent;
            }
            return null;
        },
        querySelectorAll(sel) {
            const want = sel.replace(/^:scope\s*>\s*/, '').replace(/^\./, '');
            const out = [];
            const walk = (n) => {
                (n.children || []).forEach((c) => {
                    if (c.classes && c.classes.includes(want)) out.push(c);
                    walk(c);
                });
            };
            walk(this);
            return out;
        },
        querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    };
    node.children.forEach((c) => { c.parent = node; });
    return node;
}



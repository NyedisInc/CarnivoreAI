/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve as resolvePath } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import Renderer from './Renderer.svelte';
import { checkMarkdownSafeViolation } from './markdown-safe';
import * as V from './validate';

const t = (key: string): string => key;
const ANTHROPIC_KEY = ['sk', 'ant', 'api03', 'aB3dE5fG7h'.repeat(4)].join('-');
const GITHUB_KEY = ['ghp', 'aB3dE5fG7h'.repeat(4)].join('_');
const DECLARED: V.Declared = { routes: ['refresh'], tools: ['clock_now'] };
const text = (value: unknown): Record<string, unknown> => ({ type: 'text', value });
const doc = (root: unknown): Record<string, unknown> => ({ schema: 1, root });

function nested(n: number): Record<string, unknown> {
    let node: Record<string, unknown> = text('deep');
    for (let i = 0; i < n; i += 1) node = { type: 'column', children: [node] };
    return node;
}

const NEGATIVE: [string, unknown, string][] = [
    ['an action naming an undeclared route', doc({ type: 'button', label: 'go', action: { call: 'route', route: 'wipe' } }), 'action_not_declared'],
    ['a tool the plugin did not declare', doc({ type: 'button', label: 'go', action: { call: 'tool', name: 'rm_rf' } }), 'action_not_declared'],
    ['an action kind outside route and tool', doc({ type: 'button', label: 'go', action: { call: 'link', url: 'x' } }), 'action_not_supported'],
    ['depth past the limit', doc(nested(14)), 'too_deep'],
    ['a key-shaped value', doc(text(`token ${ANTHROPIC_KEY}`)), 'secret_shape'],
    ['a github token', doc(text(GITHUB_KEY)), 'secret_shape'],
    ['an unknown node', doc({ type: 'iframe', src: 'x' }), 'unknown_node'],
    ['a javascript: link in a text', doc(text('javascript:alert(1)')), 'link_not_allowed'],
    ['an https link in a label', doc({ type: 'section', title: 'see https://evil.example', children: [] }), 'link_not_allowed'],
    ['a class on a node', doc({ type: 'text', value: 'hi', class: 'cu-frame__bar' }), 'unknown_field'],
    ['a style on a node', doc({ type: 'text', value: 'hi', style: 'position:fixed;inset:0' }), 'unknown_field'],
    ['a text over the length limit', doc(text('x'.repeat(2001))), 'bad_string'],
    ['an invisible character', doc(text('a‮b')), 'invisible_character'],
    ['a bad schema', { schema: 3, root: text('hi') }, 'bad_schema'],
    ['a v2 primitive under schema 1', { schema: 1, root: { type: 'sparkline', values: [1, 2, 3] } }, 'unknown_node'],
    ['a field outside the document', { schema: 1, root: text('hi'), html: '<b>' }, 'bad_document'],
    ['too many rows', doc({ type: 'table', columns: ['a'], rows: Array.from({ length: 101 }, () => ['x']) }), 'too_many_rows'],
    ['a bad badge status', doc({ type: 'badge', status: 'on-fire' }), 'bad_status'],
    ['raw script tag in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['raw iframe tag in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: "<iframe src='x'></iframe>" } }, 'html_not_allowed'],
    ['raw img onerror tag in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<img src=x onerror=alert(1)>' } }, 'html_not_allowed'],
    ['html comment in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<!-- comment -->' } }, 'html_not_allowed'],
    ['entity colon scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](javascript&#58;alert(1))' } }, 'link_not_allowed'],
    ['hex entity scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&#x6a;avascript:alert(1))' } }, 'link_not_allowed'],
    ['tab entity scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](java&#x09;script:alert(1))' } }, 'link_not_allowed'],
    ['named colon entity scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](javascript&colon;alert(1))' } }, 'link_not_allowed'],
    ['named Tab entity scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](java&Tab;script&colon;alert(1))' } }, 'link_not_allowed'],
    ['4-backtick closing fence desync in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '```\ncode\n````\n<script>alert(1)</script>\n```' } }, 'html_not_allowed'],
    ['4-tilde closing fence desync in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '~~~\ncode\n~~~~\n<script>alert(1)</script>\n~~~' } }, 'html_not_allowed'],
    ['backtick in info string fence desync in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '```lang`bad\n<script>alert(1)</script>\n```' } }, 'html_not_allowed'],
    ['backslash-escaped opening backtick in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '\\`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['triple-backslash-escaped opening backtick in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '\\\\\\`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['backslash-escaped double backtick mismatch in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '\\``<script>alert(1)</script>``' } }, 'html_not_allowed'],
    ['backslash inside inline code does not escape closing backtick', { schema: 2, root: { type: 'markdown_safe', value: '`a\\`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['multi-line inline code span single backtick bypass in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['multi-line inline code span double backtick bypass in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '``\n``<img src=x onerror=alert(1)>``' } }, 'html_not_allowed'],
    ['multi-line inline code span with prefix text bypass in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`foo\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['multi-line blockquote inline code span bypass in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> `\n> `<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['html block type 1 interrupts multi-line inline code span in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`hello\n<script>inside</script>`' } }, 'html_not_allowed'],
    ['indented code block does not open multi-line inline code span in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '    `hello\n<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['thematic break interrupts multi-line inline code span in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`hello\n---\n<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['blockquote interrupts multi-line inline code span in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`hello\n> <script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['multi-line link destination entity-split scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](\njavascrip&#x0a;t&#x3a;alert(1))' } }, 'link_not_allowed'],
    ['multi-line reference definition entity-split scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click][x]\n\n[x]:\njavascrip&#x0a;t&#x3a;alert(1)' } }, 'link_not_allowed'],
    ['multi-line angle-bracket link destination in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](\n  <javascript:alert(1)>)' } }, 'link_not_allowed'],
    ['ordered list 2. does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n2. `<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['ordered list 2) does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n2) `<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['ordered list 0. does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n0. `<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['empty + list item does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n+\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['empty * list item does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n*\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['empty * space list item does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n* \n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['empty 1. list item does not interrupt paragraph in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '`\n1.\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['empty 1. list item after indented blank line in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '    \nfoo `\n1. \n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['setext === inside list item does not interrupt in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '- `\n===\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['setext === across lazy blockquote does not interrupt in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> `\n===\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['setext -- inside list item does not interrupt in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '- `\n--\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['setext -- across lazy blockquote does not interrupt in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> `\n--\n`<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['ordered list 2. inside blockquote does not interrupt in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> `\n> 2. `<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['escaped bracket reference definition entity-split scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click][a\\]b]\n\n[a\\]b]: javascrip&#x0a;t&#x3a;alert(1)' } }, 'link_not_allowed'],
    ['blockquote escaped bracket reference definition entity-split scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> [click][a\\]b]\n>\n> [a\\]b]: javascrip&#x0a;t&#x3a;alert(1)' } }, 'link_not_allowed'],
    ['backslash-escaped colon in entity-split javascript link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](javascrip&#x0a;t\\:alert\\(1\\))' } }, 'link_not_allowed'],
    ['backslash-escaped colon in tab entity-split javascript link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](javascrip&#x09;t\\:alert\\(1\\))' } }, 'link_not_allowed'],
    ['backslash-escaped colon in entity-split javascript ref def in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click][x]\n\n[x]: javascrip&#x0a;t\\:alert(1)' } }, 'link_not_allowed'],
    ['backslash-escaped colon in entity-split javascript image in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '![alt](javascrip&#x0a;t\\:alert\\(1\\))' } }, 'link_not_allowed'],
    ['backslash-escaped colon in entity-split data link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](dat&#x0a;a\\:text/html,hi)' } }, 'link_not_allowed'],
    ['backslash-escaped colon in entity-split vbscript link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](vbscrip&#x0a;t\\:msgbox\\(1\\))' } }, 'link_not_allowed'],
    ['backslash-escaped colon in https link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](https\\://evil.com)' } }, 'link_not_allowed'],
    ['backslash-escaped colon in https image in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '![alt](https\\://evil.com/x.png)' } }, 'link_not_allowed'],
    ['backslash-escaped colon in https ref def in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click][x]\n\n[x]: https\\://evil.com' } }, 'link_not_allowed'],
    ['blockquote multiline label with backslash-escaped https ref def in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> [a\n> b]: https\\://evil.com\n>\n> [click][a\n> b]' } }, 'link_not_allowed'],
    ['blockquote multiline inline link destination in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> [click](\n> javascrip&#x0a;t&#x3a;alert(1))' } }, 'link_not_allowed'],
    ['blockquote space multiline inline link destination in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> [click]( \n> javascrip&#x0a;t&#x3a;alert(1))' } }, 'link_not_allowed'],
    ['list then blockquote multiline inline link destination in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '- > [click](\n  > javascrip&#x0a;t&#x3a;alert(1))' } }, 'link_not_allowed'],
    ['blockquote then list multiline inline link destination in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> - [click](\n>   javascrip&#x0a;t&#x3a;alert(1))' } }, 'link_not_allowed'],
    ['escaped paren and title with backslash-escaped https in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](https\\://a\\)b "title")' } }, 'link_not_allowed'],
    ['angle-bracket leading-space ref def in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click][x]\n\n[x]: < javascrip&#x0a;t\\:alert(1)>' } }, 'link_not_allowed'],
    ['https autolink rejected in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<https://evil.com>' } }, 'link_not_allowed'],
    ['javascript autolink rejected in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<javascript:alert(1)>' } }, 'link_not_allowed'],
    ['email autolink rejected in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<user@example.com>' } }, 'link_not_allowed'],
    ['ensp entity link scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&ensp;https://evil.com)' } }, 'link_not_allowed'],
    ['hairsp entity image scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> - ![alt](&hairsp;javascrip&#x0a;t\\:alert\\(1\\))' } }, 'link_not_allowed'],
    ['thinsp entity image scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '0. ![alt](&thinsp;vbscrip&#x09;t&colon;//evil.com)' } }, 'link_not_allowed'],
    ['NonBreakingSpace entity link scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&NonBreakingSpace;https://evil.com)' } }, 'link_not_allowed'],
    ['ensp plain text scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: 'hello&ensp;http://x' } }, 'link_not_allowed'],
    ['php processing instruction block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<?php echo 1; ?>' } }, 'html_not_allowed'],
    ['xml processing instruction block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<?xml version="1.0"?>' } }, 'html_not_allowed'],
    ['inline php processing instruction in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '- `\n- > *** <?php echo 1; ?>' } }, 'html_not_allowed'],
    ['list-nested php processing instruction in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: 'foo\n- 2. <?php echo 1; ?>' } }, 'html_not_allowed'],
    ['nbsp 1-char scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&nbsp;a:1)' } }, 'link_not_allowed'],
    ['nbsp 1-char image scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '- > ![alt](&nbsp;a\\:alert\\(1\\))' } }, 'link_not_allowed'],
    ['unicode Zs 1-char scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](\u2002a:1)' } }, 'link_not_allowed'],
    ['protocol-relative link after nbsp in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '> [click](\u00a0//evil.com)' } }, 'link_not_allowed'],
    ['protocol-relative link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](//evil.com)' } }, 'link_not_allowed'],
    ['vertical tab entity in link scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](javascrip&#x0b;t:alert(1))' } }, 'link_not_allowed'],
    ['code span vs link title precedence in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[a](b "`") <script>alert(1)</script> `x`' } }, 'html_not_allowed'],
    ['code span vs html attr precedence in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<span title="`"><script>alert(1)</script>`x`' } }, 'html_not_allowed'],
    ['unclosed php block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<?php echo 1' } }, 'html_not_allowed'],
    ['unclosed doctype declaration block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<!DOCTYPE html' } }, 'html_not_allowed'],
    ['unclosed cdata block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<![CDATA[ alert(1)' } }, 'html_not_allowed'],
    ['unclosed div block in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '<div' } }, 'html_not_allowed'],
    ['alphanumeric emsp13 entity link in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&emsp13;https://evil.com)' } }, 'link_not_allowed'],
    ['alphanumeric emsp14 entity 1-char scheme in markdown_safe', { schema: 2, root: { type: 'markdown_safe', value: '[click](&emsp14;a:1)' } }, 'link_not_allowed'],
    ['wide list 100. followed by 4-space backtick fence and script', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ```\n<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['wide list 100. followed by 4-space tilde fence and script', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ~~~\n<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['wide list 1000. followed by 5-space backtick fence and script', { schema: 2, root: { type: 'markdown_safe', value: '1000. foo\n     ```\n<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['wide list 100. followed by 4-space fence and img onerror', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ```\n<img src=x onerror=alert(1)>' } }, 'html_not_allowed'],
    ['wide list 100. followed by 4-space fence and php tag', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ```\n<?php echo 1' } }, 'html_not_allowed'],
    ['wide list 100. followed by 4-space fence and protocol-relative link', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ```\n[x](//evil.com)' } }, 'link_not_allowed'],
    ['wide list 100. followed by 4-space fence and 1-char scheme link', { schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    ```\n[x](a:1)' } }, 'link_not_allowed'],
    ['blockquote wide list 100. followed by 4-space fence and script', { schema: 2, root: { type: 'markdown_safe', value: '> 100. foo\n>     ```\n> <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['wide list 100. unclosed backtick interrupted by 4-space fence', { schema: 2, root: { type: 'markdown_safe', value: '100. `foo\n    ```\n<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['wide list 100. unclosed backtick interrupted by 4-space div', { schema: 2, root: { type: 'markdown_safe', value: '100. `foo\n    <div>\n<script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['blockquote wide list 100. unclosed backtick interrupted by 4-space fence', { schema: 2, root: { type: 'markdown_safe', value: '> 100. `foo\n>     ```\n> <script>alert(1)</script>`' } }, 'html_not_allowed'],
    ['blockquote deep-indent continuation > after indented code', { schema: 2, root: { type: 'markdown_safe', value: '>     ```\n    > <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['blockquote deep-indent continuation > after wide list', { schema: 2, root: { type: 'markdown_safe', value: '> 100. foo\n    > <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def followed by script', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def followed by heading script', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n# <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def followed by blockquote script', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n> <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def followed by fence and script', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n```\n```\n<script>alert(1)</script>' } }, 'html_not_allowed'],
    ['blockquote trailing backslash ref-def followed by script', { schema: 2, root: { type: 'markdown_safe', value: '> [a]: x\\\n> <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['wide list trailing backslash ref-def followed by 5-space script', { schema: 2, root: { type: 'markdown_safe', value: '100. [a]: x\\\n     <script>alert(1)</script>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def followed by multiline div', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n<div\nonclick=1>' } }, 'html_not_allowed'],
    ['trailing backslash ref-def title backtick desync script', { schema: 2, root: { type: 'markdown_safe', value: '[a]: x\\\n"`"\n`<script>alert(1)</script>`\n\n[a]' } }, 'html_not_allowed'],
    ['multiline inline link backslash newline protocol-relative', { schema: 2, root: { type: 'markdown_safe', value: '[a](//evil.com\\\ny)' } }, 'link_not_allowed'],
    ['multiline angle inline link backslash newline protocol-relative', { schema: 2, root: { type: 'markdown_safe', value: '[a](<//evil.com\\\ny>)' } }, 'link_not_allowed'],
    ['inline open tag uni+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=1\u00a0y =2>' } }, 'html_not_allowed'],
    ['block open tag uni+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: '<a x=1\u00a0y =2>' } }, 'html_not_allowed'],
    ['inline open tag double nbsp uni+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=\u00a0\u00a0y =2>' } }, 'html_not_allowed'],
    ['inline open tag uni+newline ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=1\u00a0y\n=2>' } }, 'html_not_allowed'],
    ['inline open tag uni+ascii ws single-quoted val', { schema: 2, root: { type: 'markdown_safe', value: "a <a x=1\u00a0y ='2'>" } }, 'html_not_allowed'],
    ['inline open tag uni+ascii ws double-quoted val', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=1\u00a0y ="2">' } }, 'html_not_allowed'],
    ['inline open tag multi-attr uni+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=1\u00a0y=2\u00a0z =3>' } }, 'html_not_allowed'],
    ['inline open tag leading nbsp val uni+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=\u00a01\u00a0y =2>' } }, 'html_not_allowed'],
    ['inline open tag u2002+ascii ws before =', { schema: 2, root: { type: 'markdown_safe', value: 'a <a x=1\u2002y =2>' } }, 'html_not_allowed'],
    ['unclosed bracket backticksScanned img onerror bypass', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`a`' } }, 'html_not_allowed'],
    ['fuzz backticksScanned close-tag bypass', { schema: 2, root: { type: 'markdown_safe', value: '\\\\<)[`--->\n</a></divhttps:`\\\\`\u3000``' } }, 'html_not_allowed'],
    ['unclosed image bracket backticksScanned img onerror', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x onerror=alert(1)>`a`' } }, 'html_not_allowed'],
    ['closed link backticksScanned img onerror', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`a`](ok)' } }, 'html_not_allowed'],
    ['nested unclosed bracket backticksScanned script', { schema: 2, root: { type: 'markdown_safe', value: '[[`<script>`] `' } }, 'html_not_allowed'],
    ['full-ref ][ unclosed backtick img onerror bypass', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref ][ space unclosed backtick script bypass', { schema: 2, root: { type: 'markdown_safe', value: '[`<script>alert(1)</script>`][ `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref image ][ unclosed backtick img onerror bypass', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref ][ immediate unclosed backtick img onerror', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref ][ closed ref bracket with unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][a `]\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref ][ nested [a] with unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][[a] `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref ][ closed code span + unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][`a` `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['full-ref nested [[...]][ unclosed backtick img onerror', { schema: 2, root: { type: 'markdown_safe', value: '[[`<img src=x>`]][`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['inline-link fallback pos+1 ref label unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['matched full-ref with unclosed backtick in ref label', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][a `]\n\n[a `]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link x/]) unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](x/]) unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link <x/]> unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](<x/]>) unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link <]> ) unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](<]> ) `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link <]>) unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](<]>) `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline image x/]) unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][![a](x/]) unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline image <]>) unclosed backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][![a](<]>) `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link script x/])', { schema: 2, root: { type: 'markdown_safe', value: '[`<script>alert(1)</script>`][[a](x/]) `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link dquote title ]', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](x "t]") unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link b dquote title ]', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](b "]") `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link squote title ]', { schema: 2, root: { type: 'markdown_safe', value: "[`<img src=x onerror=alert(1)>`][[a](x 't]') unclosed `\n\n[a]: ok" } }, 'html_not_allowed'],
    ['ref nested inline link paren title ]', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](x (])) unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline link paren text title ]', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](x (t])) unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref nested inline image dquote title ]', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][![a](x "t]") unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image paren fallback to link a c[', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image paren fallback to link img onerror', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x onerror=alert(1)>`](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image paren fallback closed ref a c[a `]', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](a c[a `]\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image angle paren fallback script <[', { schema: 2, root: { type: 'markdown_safe', value: '![`<script>alert(1)</script>`](<[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image angle paren fallback script <[unclosed', { schema: 2, root: { type: 'markdown_safe', value: '![`<script>alert(1)</script>`](<[unclosed `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image with unmatched [b] paren fallback', { schema: 2, root: { type: 'markdown_safe', value: '![ [b] `<img src=x>` ](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image angle paren space fallback <[ ', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](<[ `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image angle paren text fallback <[a ', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](<[a `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image title paren fallback x "[ ', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](x "[ `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image nested paren fallback (([ ', { schema: 2, root: { type: 'markdown_safe', value: '![`<img src=x>`](([ `\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image with nested inline image paren fallback', { schema: 2, root: { type: 'markdown_safe', value: '![ ![a](b) `<img src=x>` ](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image with nested unmatched ![a] paren fallback', { schema: 2, root: { type: 'markdown_safe', value: '![ ![a] `<img src=x>` ](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['image with nested matched image containing link paren fallback', { schema: 2, root: { type: 'markdown_safe', value: '![ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['outer link with matched image containing link paren fallback', { schema: 2, root: { type: 'markdown_safe', value: '[ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok' } }, 'html_not_allowed'],
    ['ref invalid javascript autolink backtick', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`][<javascript:`>]\n\n[<javascript:`>]: ok' } }, 'link_not_allowed'],
    ['ref data:image/png inline link x/]) rejected', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x onerror=alert(1)>`][[a](data:image/png;base64,x/]) `\n\n[a]: ok' } }, 'link_not_allowed'],
    ['ref nested ![ ![a][ [b](c) ] ] hLink propagation', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>` [top][ ![ ![a][ [b](c) ] ](([r](x/]) (`\n\n[top]: ok\n[r]: ok' } }, 'html_not_allowed'],
    ['inline paren tail javascript:1 validateLink fallback', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>` [top][ [a](javascript:1 ([b](y/]) (`\n\n[top]: ok\n[b]: ok' } }, 'html_not_allowed'],
    ['inline paren tail javascript:x fallback rejected', { schema: 2, root: { type: 'markdown_safe', value: '[`<img src=x>`](javascript:x [b] `<script>1</script>\n\n[b]: ok' } }, 'link_not_allowed'],
    [
        'duplicate form control names (input + select)',
        {
            schema: 2,
            root: {
                type: 'form',
                action: { call: 'route', route: 'refresh' },
                children: [
                    { type: 'input', name: 'dup_field', label: 'A' },
                    { type: 'select', name: 'dup_field', label: 'B', options: ['one'] },
                ],
            },
        },
        'duplicate_field_name',
    ],
    [
        'nested duplicate form control names (textarea + toggle)',
        {
            schema: 2,
            root: {
                type: 'form',
                action: { call: 'route', route: 'refresh' },
                children: [
                    { type: 'row', children: [{ type: 'textarea', name: 'dup_field', label: 'A' }] },
                    { type: 'toggle', name: 'dup_field', label: 'B' },
                ],
            },
        },
        'duplicate_field_name',
    ],
];

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(document_: unknown, extra: Record<string, unknown> = {}): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Renderer, { target, props: { cplugId: 'acme-clock', name: 'Acme Clock', document: document_, declared: DECLARED, t, ...extra } });
    await tick(); await tick();
    flushSync();
    return target;
}

const SERVER = readFileSync(resolvePath(__dirname, '../../../../src/plugins/host/ui_doc.py'), 'utf8');

describe('client validation mirrors the server', () => {
    test('every limit and the node vocabulary are the same numbers and fields as ui_doc.py', () => {
        const limit = (name: string): number => {
            const m = new RegExp(`^${name} = (\\d+)( \\* (\\d+))?$`, 'm').exec(SERVER);
            expect(m, `${name} not found in ui_doc.py`).not.toBeNull();
            return Number(m![1]) * (m![3] ? Number(m![3]) : 1);
        };
        for (const name of ['MAX_NODES', 'MAX_DEPTH', 'MAX_BYTES', 'MAX_ROWS', 'MAX_COLUMNS', 'MAX_TEXT', 'MAX_LABEL', 'MAX_PAYLOAD_BYTES']) {
            expect((V as unknown as Record<string, number>)[name], name).toBe(limit(name));
        }
        const block = /_FIELDS: Dict\[str, frozenset\] = \{([\s\S]*?)\n\}/.exec(SERVER)![1]!;
        const server: Record<string, string[]> = {};
        for (const m of block.matchAll(/"(\w+)": frozenset\(\{([^}]*)\}\)/g)) server[m[1]!] = [...m[2]!.matchAll(/"(\w+)"/g)].map((x) => x[1]!).sort();
        const client = Object.fromEntries(Object.entries(V.NODE_FIELDS).map(([k, v]) => [k, [...v].sort()]));
        expect(client).toEqual(server);
        const setOf = (name: string): string[] => [...new RegExp(`^${name} = frozenset\\(\\{([^}]*)\\}\\)`, 'm').exec(SERVER)![1]!.matchAll(/"(\w+)"/g)].map((x) => x[1]!).sort();
        expect([...V.TONES].sort()).toEqual(setOf('TONES'));
        const vocab = readFileSync(resolvePath(__dirname, '../../../../src/models/activity_status.py'), 'utf8');
        const literal = /^ActivityStatus = Literal\[([\s\S]*?)\]/m.exec(vocab)![1]!;
        expect([...V.STATUSES].sort()).toEqual([...literal.matchAll(/"(\w+)"/g)].map((x) => x[1]!).sort());
    });

    test.each(NEGATIVE)('refuses %s with the server code', (_name, document_, code) => {
        const verdict = V.validateDocument(document_, DECLARED);
        expect(verdict.ok).toBe(false);
        if (!verdict.ok) expect(verdict.code).toBe(code);
    });

    test('a valid document passes, rebuilt with only known fields', () => {
        const valid = {
            schema: 1,
            root: { type: 'section', title: 'clock', children: [
                { type: 'row', gap: 2, children: [{ type: 'badge', status: 'working' }, text({ bind: '/now' })] },
                { type: 'meter', label: 'load', value: 3, max: 10, thresholds: [5, 8] },
                { type: 'button', label: 'refresh', action: { call: 'route', route: 'refresh', payload: { full: true } } },
            ] },
            data: { now: '12:00' },
        };
        const verdict = V.validateDocument(valid, DECLARED);
        expect(verdict.ok).toBe(true);
        expect(V.resolve({ bind: '/now' }, (verdict as { doc: V.UiDocument }).doc.data)).toBe('12:00');
    });
});

describe('Renderer and HostFrame', () => {
    test('a valid document draws its nodes inside the plugin box', async () => {
        const root = await draw({ schema: 1, root: { type: 'column', children: [text('hello'), { type: 'stat', label: 'n', value: 7 }] } });
        const box = root.querySelector('[data-cplug-box]')!;
        expect(box.textContent).toContain('hello');
        expect(box.querySelector('[data-cu="stat"]')).not.toBeNull();
    });

    test('the literal name and the third-party mark sit OUTSIDE the box, before it, and a hostile document cannot remove them', async () => {
        for (const hostile of [doc(text('x'.repeat(2000))), doc(nested(3)), doc({ type: 'text', value: 'hi', class: 'cu-frame__bar', style: 'display:none' }), doc({ type: 'iframe' })]) {
            const root = await draw(hostile);
            const name = root.querySelector('[data-cplug-name]')!;
            const mark = root.querySelector('[data-cplug-mark]')!;
            const box = root.querySelector('[data-cplug-box]');
            expect(name.textContent).toBe('Acme Clock');
            expect(mark.textContent).toBe('cplug_ui.mark.third_party');
            expect(box?.contains(mark) ?? false).toBe(false);
            expect(box?.contains(name) ?? false).toBe(false);
            if (box) expect(mark.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
            unmount(mounted!); mounted = null; document.body.innerHTML = '';
        }
    });

    test('a refused document draws NOTHING of the plugin and shows the host line; a sideload reads unverified', async () => {
        const root = await draw(doc({ type: 'iframe' }), { unverified: true });
        expect(root.querySelector('[data-cu-root]')).toBeNull();
        expect(root.querySelector('[data-cplug-note]')?.textContent).toBe('cplug_ui.could_not_draw');
        expect(root.querySelector('[data-cplug-mark]')?.textContent).toBe('cplug_ui.mark.unverified');
    });

    test('a button runs only its declared route; a 409 not running shows the quiet host line', async () => {
        const { ApiError } = await import('../../opscenter/api/auth.svelte');
        const run = vi.fn(async () => { throw new ApiError('x', 409, 'cplug_not_running'); });
        const root = await draw(doc({ type: 'button', label: 'refresh', action: { call: 'route', route: 'refresh' } }), { run });
        root.querySelector<HTMLElement>('[data-cu="button"] button')!.click();
        await tick(); await tick(); flushSync();
        expect(run).toHaveBeenCalledExactlyOnceWith({ call: 'route', route: 'refresh' });
        expect(root.querySelector('.cu-action__line')?.textContent).toBe('cplug_ui.not_running');
    });

    test('a button with a declared tool action is enabled and invokes run with the tool action', async () => {
        const run = vi.fn(async () => undefined);
        const action = { call: 'tool', name: 'clock_now', payload: { tz: 'UTC' } };
        const root = await draw(doc({ type: 'button', label: 'check', action }), { run });
        const btn = root.querySelector<HTMLButtonElement>('[data-cu="button"] button')!;
        expect(btn.disabled).toBe(false);
        btn.click();
        await tick(); await tick(); flushSync();
        expect(run).toHaveBeenCalledExactlyOnceWith(action);
    });

    test('schema 2 validates all 21 primitives including interactive form, tabs, and rich readouts', () => {
        const docV2 = {
            schema: 2,
            root: {
                type: 'section',
                title: 'v2 controls',
                children: [
                    {
                        type: 'form',
                        action: { call: 'route', route: 'refresh' },
                        submit_label: 'Save',
                        children: [
                            { type: 'input', name: 'host', label: 'Host', placeholder: 'localhost', input_type: 'text', required: true },
                            { type: 'textarea', name: 'notes', label: 'Notes', rows: 3 },
                            { type: 'select', name: 'mode', label: 'Mode', options: ['fast', { value: 'deep', label: 'Deep' }], value: 'fast' },
                            { type: 'toggle', name: 'auto', label: 'Auto', checked: true, tone: 'accent' },
                        ],
                    },
                    {
                        type: 'tabs',
                        active: 'logs',
                        items: [
                            { id: 'logs', label: 'Logs', content: { type: 'code', value: 'ok', language: 'txt' } },
                            { id: 'docs', label: 'Docs', children: [{ type: 'markdown_safe', value: '**hello**' }] },
                        ],
                    },
                    { type: 'progress', label: 'Sync', value: 40, max: 100, tone: 'normal' },
                    { type: 'empty_state', title: 'Nothing yet', description: 'Run a check', action: { call: 'tool', name: 'clock_now' } },
                    { type: 'sparkline', values: [1, 3, 2, 5], label: 'Latency', tone: 'accent' },
                ],
            },
        };
        const verdict = V.validateDocument(docV2, DECLARED);
        expect(verdict.ok).toBe(true);
        if (verdict.ok) expect(verdict.doc.schema).toBe(2);
    });

    test('markdown_safe allows code blocks/inline code and separate form scopes may reuse field names', () => {
        for (const safeValue of [
            'Use `<div>` inline or [docs](readme.md).\n\n```html\n<script>ok</script>\n```',
            '\\\\`<script>ok</script>`',
            '`` `a` <script>ok</script> ``',
            '[click](javascript&Colon;alert(1))',
            '[click](javascript&COLON;alert(1))',
            '`hello\nworld`',
            '`hello\n<span>inside</span>`',
            '`hello\nfoo <script>inside</script>`',
            '> `hello\n> world`',
            '[click](\nreadme.md)',
            '[click][x]\n\n[x]:\nreadme.md',
            '[click](java&#0;script:alert(1))',
            '[click](java&#x110000;script:alert(1))',
            '[click](javascrip&#x0a;t&#x5c;:alert(1))',
            '[click](https\\\\://evil.com)',
            '[click](https&#x5c;://evil.com)',
            '> [docs](\n> readme.md)',
            'hello &#x0b; world',
            '[click](&#x5c;:)',
            '[click](\\\\:)',
            '[time](12:30)',
            'a <? b',
            '\\<div class="x">',
            '<a + b>',
            '    <script>alert(1)</script>',
            'x&Idot;http://evil.com',
            '[a]:\\',
            '100. [a]: x\\\n    <script>alert(1)</script>',
            '[a `<script>`](ok)',
            '[ [a `<script>`](ok) `',
            '[`<script>`] `',
            '[`<script>`][a] `\n\n[a]: ok',
            '[ [a] `<img src=x>` ][`\n\n[a]: ok',
            '[`<script>`](ok) `',
            '![ [a](b) `<img src=x>` ](a c[`\n\n[a]: ok',
            '![ [a] `<img src=x>` ](a c[`\n\n[a]: ok',
            '![ ![ [a](b) ] `<img src=x>` ](a c[`\n\n[a]: ok',
            '![ ![a](b c `<img src=x>` ](d e[`\n\n[a]: ok',
            '[`<img src=x>`][[ [a](b) ](x/]) `\n\n[a]: ok',
            '[`<img src=x>`][ [a][b](c/]) `\n\n[a]: ok\n[b]: ok',
            '[`<img src=x>`](   \n\n[a]: ok',
        ]) {
            const verdict = V.validateDocument({ schema: 2, root: { type: 'markdown_safe', value: safeValue } }, DECLARED);
            expect(verdict.ok, safeValue).toBe(true);
        }
        const docSafe = {
            schema: 2,
            root: {
                type: 'column',
                children: [
                    {
                        type: 'markdown_safe',
                        value: 'Use `<div>` inline or [docs](readme.md).\n\n```html\n<script>ok</script>\n```',
                    },
                    {
                        type: 'form',
                        action: { call: 'route', route: 'refresh' },
                        children: [{ type: 'input', name: 'query', label: 'Q1' }],
                    },
                    {
                        type: 'form',
                        action: { call: 'route', route: 'refresh' },
                        children: [{ type: 'input', name: 'query', label: 'Q2' }],
                    },
                ],
            },
        };
        const verdict = V.validateDocument(docSafe, DECLARED);
        expect(verdict.ok).toBe(true);
    });

    test('wide-list tab-indented fence and nested-bracket linear-time stress cases', () => {
        for (const [tabPayload, expectedTabCode] of [
            ['1000. foo\n\t```\n<script>alert(1)</script>', 'html_not_allowed'],
            ['100. foo\n    <script>alert(1)</script>', null],
            ['> >   > \t> <a title=">">\n', 'html_not_allowed'],
            ['> > 1.   \t<a title=">">\n# h\nlazy', 'html_not_allowed'],
            ['> >   > \t<a x=1\u00a0y =2>', 'html_not_allowed'],
            ['> - > > \t<a title=">">', 'html_not_allowed'],
            ['> >   > \t<script>alert(1)</script>', 'html_not_allowed'],
            ['> >   > \t<img src=x onerror=alert(1)>', 'html_not_allowed'],
            ['> > 1.   \t<img src=x onerror=alert(1)>', 'html_not_allowed'],
            ['> - > > \t<img src=x onerror=alert(1)>', 'html_not_allowed'],
            ['> >   > \t[click](//evil.com)', 'link_not_allowed'],
            ['> > 1.   \t[click](//evil.com)', 'link_not_allowed'],
            ['> - > > \t[click](//evil.com)', 'link_not_allowed'],
            ['> > \t<script>alert(1)</script>', null],
            ['> >   \t<script>alert(1)</script>', null],
            ['-\n\n    `foo\n<script>alert(1)</script>`', 'html_not_allowed'],
            ['> -\n>\n>     `foo\n> <script>alert(1)</script>`', 'html_not_allowed'],
            ['- - -\n    `a\n<script>alert(1)</script>`', 'html_not_allowed'],
        ] as const) {
            expect(checkMarkdownSafeViolation(tabPayload), tabPayload).toBe(expectedTabCode);
        }
        expect(V.validateDocument({ schema: 2, root: { type: 'markdown_safe', value: '100. foo\n    <script>alert(1)</script>' } }, DECLARED).ok).toBe(true);

        const cases: [string, boolean, string | null][] = [
            ['['.repeat(64) + ']'.repeat(64), true, null],
            ['['.repeat(500) + ']'.repeat(500), true, null],
            ['['.repeat(300) + 'a' + ']('.repeat(100) + 'b)', true, null],
            ['!['.repeat(400) + 'a' + ']('.repeat(200), true, null],
            ['['.repeat(1000), true, null],
            ['[['.repeat(400) + 'a](javascript:alert(1))' + ']]'.repeat(200), false, 'link_not_allowed'],
        ];
        for (const [payload, expectedOk, expectedCode] of cases) {
            const t0 = performance.now();
            const verdict = V.validateDocument({ schema: 2, root: { type: 'markdown_safe', value: payload } }, DECLARED);
            const elapsedMs = performance.now() - t0;
            expect(verdict.ok).toBe(expectedOk);
            if (!verdict.ok) expect(verdict.code).toBe(expectedCode);
            expect(elapsedMs).toBeLessThan(50);
        }
    });

    test('HTML attribute ReDoS, unclosed EOF scans under 50ms, and Unicode whitespace attr parity', () => {
        const timingCases: [string, boolean, string | null][] = [
            ['a <a ' + 'x=\u00a0\u00a0 '.repeat(50), true, null],
            ['<a ' + 'x=\u00a0\u00a0 '.repeat(50), true, null],
            ['a <a x=' + '\u00a0'.repeat(1900), true, null],
            ['<a x=' + '\u00a0'.repeat(1900), true, null],
            ['a <a x=' + '\u00a0'.repeat(1900) + ' y=', true, null],
            ['<a x=' + '\u00a0'.repeat(1900) + ' y=', true, null],
            ['a ' + '<!--'.repeat(450), true, null],
            ['a ' + '<!-- a ---> '.repeat(150), true, null],
            ['a ' + '<?'.repeat(900), true, null],
            ['a ' + '<![CDATA['.repeat(200), true, null],
            ['a ' + '<!A'.repeat(500), true, null],
            ['a ' + '<div '.repeat(399), true, null],
            ['a ' + '<a '.repeat(500) + '>', false, 'html_not_allowed'],
            ['a ' + '<a x=1 '.repeat(250) + '>', false, 'html_not_allowed'],
            ['a <a ' + 'x=1\u00a0y '.repeat(200), true, null],
            ['[`' + 'a`'.repeat(500), true, null],
            ['[`a`]['.repeat(200) + '`\n\n[a]: ok', true, null],
            ['[a]'.repeat(200) + '[`\n\n[a]: ok', true, null],
            ['[a][' + '[b](x/]) '.repeat(200) + '`\n\n[a]: ok', true, null],
            ['[a][' + '[b](x ['.repeat(240) + ']'.repeat(240) + '\n\n[a]: ok', true, null],
            ['[a][' + '[b](x ['.repeat(260) + '`\n\n[a]: ok', true, null],
            ['![a][' + '![b](x/]) '.repeat(190) + '`\n\n[a]: ok', true, null],
        ];
        for (const [payload, expectedOk, expectedCode] of timingCases) {
            const t0 = performance.now();
            const verdict = V.validateDocument({ schema: 2, root: { type: 'markdown_safe', value: payload } }, DECLARED);
            const elapsedMs = performance.now() - t0;
            expect(verdict.ok).toBe(expectedOk);
            if (!verdict.ok) expect(verdict.code).toBe(expectedCode);
            expect(elapsedMs).toBeLessThan(50);
        }

        for (const [directBomb, expectedCode] of [
            ['a ' + '<div '.repeat(400), null],
            ['[a][' + '[b](x/]) '.repeat(300) + '`\n\n[a]: ok', null],
            ['[a][' + '[b](x ['.repeat(500) + ']'.repeat(500) + '\n\n[a]: ok', null],
            ['[a][' + '[b](x ['.repeat(500) + '`\n\n[a]: ok', null],
            ['![a][' + '![b](x/]) '.repeat(300) + '`\n\n[a]: ok', null],
            ['[top][' + '[a]['.repeat(4000) + 'b' + ']'.repeat(4000) + ']\n\n[top]: ok\n[b]: ok', null],
            ['[top][' + '\\[a\\]['.repeat(4000) + 'b' + ']'.repeat(4000) + ']\n\n[top]: ok\n[b]: ok', null],
            ['[top][' + '['.repeat(4000) + '[b]' + ']'.repeat(4000) + ']\n\n[top]: ok\n[b]: ok', null],
            ['[top][' + '['.repeat(4000) + '[b]' + ']'.repeat(4000) + '] <script>1</script>\n\n[top]: ok\n[b]: ok', 'html_not_allowed'],
            ['[top][' + '\\[a\\]['.repeat(4000) + 'b' + ']'.repeat(4000) + '] <script>1</script>\n\n[top]: ok\n[b]: ok', 'html_not_allowed'],
            ['- '.repeat(4000) + 'x\n' + '\n'.repeat(4000), null],
            ['- '.repeat(4000) + 'x\n' + '\n'.repeat(4000) + '<script>1</script>', 'html_not_allowed'],
            ['- '.repeat(4000) + '```\n' + '\n'.repeat(4000) + '```', null],
            ['- '.repeat(4000) + 'x\n' + 'y\n'.repeat(4000), null],
            ['- '.repeat(4000) + 'x\n' + 'y\n'.repeat(4000) + '<script>1</script>', 'html_not_allowed'],
            ['> '.repeat(4000) + 'x\n' + 'y\n'.repeat(4000), null],
            ['> '.repeat(4000) + 'x\n' + 'y\n'.repeat(4000) + '<script>1</script>', 'html_not_allowed'],
            ['- '.repeat(4000) + '[a\n' + 'y\n'.repeat(4000), null],
            ['> ' + '- '.repeat(4000) + 'x\n' + '>\n'.repeat(4000), null],
            ['> ' + '- '.repeat(4000) + 'x\n' + '>\n'.repeat(4000) + '> <script>1</script>', 'html_not_allowed'],
            ['- '.repeat(4000) + 'x\n' + '  '.repeat(4000) + 'x', null],
            ['- '.repeat(4000) + 'x\n' + '  '.repeat(4000) + 'x<script>1</script>', 'html_not_allowed'],
            ['> \t'.repeat(2000) + '- \t'.repeat(2000) + 'x\n' + 'y\n'.repeat(4000), null],
            ['> \t'.repeat(2000) + '- \t'.repeat(2000) + 'x\n' + 'y\n'.repeat(4000) + '<script>1</script>', 'html_not_allowed'],
            ['- '.repeat(4000) + '- - -', null],
        ] as const) {
            const tDiv = performance.now();
            expect(checkMarkdownSafeViolation(directBomb)).toBe(expectedCode);
            expect(performance.now() - tDiv).toBeLessThan(50);
        }
        expect(checkMarkdownSafeViolation('[`<img src=x>`](javascript:x [b] `<script>1</script>\n\n[b]: ok')).toBe('html_not_allowed');

        for (const ctrlPayload of ['a <a x=1\u00a0y\t=2>', 'a <a x=1\u00a0y\x0c=2>', 'a <a x=1\u00a0y\x0b=2>']) {
            expect(checkMarkdownSafeViolation(ctrlPayload), ctrlPayload).toBe('html_not_allowed');
        }

        const parityCases: [string, boolean, string | null][] = [
            ['a <a x=\u00a0b>', false, 'html_not_allowed'],
            ['a <a x=\u00a0>', false, 'html_not_allowed'],
            ['<a x=\u00a0>', false, 'html_not_allowed'],
            ['<a x=\u00a0b>', false, 'html_not_allowed'],
            ['a <a x=1\u00a02>', false, 'html_not_allowed'],
            ['a <a x=\u00a0\u00a0y=1>', false, 'html_not_allowed'],
            ['a <!----> b', false, 'html_not_allowed'],
            ['a <a x=\u00a0y=1>', true, null],
            ['a <a x= >', true, null],
            ['<a x= >', true, null],
            ['a <!-- a ---> b', true, null],
        ];
        for (const [payload, expectedOk, expectedCode] of parityCases) {
            const verdict = V.validateDocument({ schema: 2, root: { type: 'markdown_safe', value: payload } }, DECLARED);
            expect(verdict.ok, payload).toBe(expectedOk);
            if (!verdict.ok) expect(verdict.code, payload).toBe(expectedCode);
        }
    });

    test('html5-entities.json covers all 2,125 HTML5 entities without whitespace/scheme bypasses', () => {
        const entities = JSON.parse(readFileSync(resolvePath(__dirname, './html5-entities.json'), 'utf8')) as Record<string, string>;
        const keys = Object.keys(entities);
        expect(keys.length).toBe(2125);
        const wsRe = /[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/;
        const delimRe = /[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff(<["']/;
        for (const ent of keys) {
            const decoded = entities[ent]!;
            const isWsOrLtOnly = [...decoded].every((ch) => wsRe.test(ch) || ch === '<');
            const isSchemePrefix = /^[A-Za-z][A-Za-z0-9+.\-]*$/.test(decoded);
            const endsWithDelim = decoded.length > 0 && delimRe.test(decoded[decoded.length - 1]!);
            const linkVerdict = V.validateDocument(
                { schema: 2, root: { type: 'markdown_safe', value: `[click](&${ent};https://evil.com)` } },
                DECLARED,
            );
            const oneCharVerdict = V.validateDocument(
                { schema: 2, root: { type: 'markdown_safe', value: `[click](&${ent};a:1)` } },
                DECLARED,
            );
            const splitSchemeVerdict = V.validateDocument(
                { schema: 2, root: { type: 'markdown_safe', value: `[click](javascrip&${ent};t:alert(1))` } },
                DECLARED,
            );
            if (isWsOrLtOnly) {
                expect(linkVerdict.ok, `&${ent};https://evil.com`).toBe(false);
                expect(oneCharVerdict.ok, `&${ent};a:1`).toBe(false);
                if ([...decoded].every((ch) => wsRe.test(ch))) {
                    expect(splitSchemeVerdict.ok, `javascrip&${ent};t:alert(1)`).toBe(false);
                }
            } else if (isSchemePrefix) {
                expect(linkVerdict.ok, `&${ent};https://evil.com`).toBe(false);
                expect(oneCharVerdict.ok, `&${ent};a:1`).toBe(false);
            } else if (endsWithDelim) {
                expect(linkVerdict.ok, `&${ent};https://evil.com`).toBe(false);
                expect(oneCharVerdict.ok, `&${ent};a:1`).toBe(true);
            } else {
                expect(linkVerdict.ok, `&${ent};https://evil.com`).toBe(true);
                expect(oneCharVerdict.ok, `&${ent};a:1`).toBe(true);
            }
        }
    });

    test('resolve ignores Object.prototype keys when traversing data pointers', () => {
        expect(V.resolve({ bind: '/toString' }, { a: 1 })).toBe('');
        expect(V.resolve({ bind: '/constructor/name' }, { a: 1 })).toBe('');
        expect(V.resolve({ bind: '/a' }, { a: 42 })).toBe(42);
    });
});

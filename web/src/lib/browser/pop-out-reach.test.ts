import { describe, expect, test } from 'vitest';
import { isLoopbackHost, realPageReach } from './pop-out-reach';

describe('the real page reach', () => {
    test.each(['localhost', 'LOCALHOST', 'app.localhost', '127.0.0.1', '127.1.2.3', '[::1]', '0.0.0.0', 'localhost.'])(
        '%s is loopback',
        (host) => expect(isLoopbackHost(host)).toBe(true),
    );

    test.each(['10.0.0.6', 'mini.lan', 'example.com', 'localhost.example.com', '128.0.0.1'])('%s is not loopback', (host) =>
        expect(isLoopbackHost(host)).toBe(false),
    );

    test('a loopback address is refused off the host and offered on it', () => {
        expect(realPageReach('http://localhost:3000/app', 'carnivore.lan')).toEqual({ ok: false, reason: 'host_only' });
        expect(realPageReach('http://127.0.0.1:8080/', '10.0.0.6')).toEqual({ ok: false, reason: 'host_only' });
        expect(realPageReach('http://localhost:3000/app', 'localhost')).toEqual({ ok: true, url: 'http://localhost:3000/app' });
        expect(realPageReach('http://[::1]:3000/', '127.0.0.1')).toEqual({ ok: true, url: 'http://[::1]:3000/' });
    });

    test('a LAN or public address is offered anywhere', () => {
        expect(realPageReach('http://10.0.0.6:3000/', 'phone.lan')).toEqual({ ok: true, url: 'http://10.0.0.6:3000/' });
        expect(realPageReach('https://example.com/docs?q=1', 'carnivore.lan')).toEqual({ ok: true, url: 'https://example.com/docs?q=1' });
    });

    test.each([null, undefined, '', 'about:blank', 'file:///etc/hosts', 'not a url'])('%j has no real page', (url) =>
        expect(realPageReach(url, 'localhost')).toEqual({ ok: false, reason: 'no_address' }),
    );
});

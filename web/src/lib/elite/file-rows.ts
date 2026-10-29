
export interface Seg {
    c: string;
    s: string;
    kind?: string;
}

export interface Layout {
    t: 'wide' | 'phone';
    f: { num: number; tag: number; name: number; kind: number; dl: number; brief: number };
}

export interface RowInput {
    name: string;
    kind: string;
    kindTag: string;
    brief: string;
    dl: number | null;
    mark: string;
    tagged: boolean;
}

export function tierOf(cols: number): 'wide' | 'phone' {
    return cols >= 56 ? 'wide' : 'phone';
}

export function layoutOf(cols: number): Layout {
    const t = tierOf(cols);
    const inner = cols - 1;
    if (t === 'wide') {
        const name = inner >= 70 ? 22 : 18;
        return { t, f: { num: 2, tag: 3, name, kind: 5, dl: 5, brief: Math.max(8, inner - 20 - name) } };
    }
    return { t, f: { num: 2, tag: 3, name: inner - 7 - 6 - 5, kind: 5, dl: 5, brief: inner - 7 } };
}

export function pad(s: string, n: number, right = false): string {
    if (s.length >= n) return s.slice(0, n);
    const p = ' '.repeat(n - s.length);
    return right ? p + s : s + p;
}

export function fit(s: string, n: number): string {
    if (n <= 0) return '';
    if (s.length <= n) return s;
    const cut = s.slice(0, n - 3);
    const at = cut.lastIndexOf(' ');
    return `${at > n * 0.5 ? cut.slice(0, at) : cut}...`;
}

export function wrap2(text: string, n: number): [string, string] {
    const words = text.split(/\s+/).filter(Boolean);
    const l: [string, string] = ['', ''];
    let i = 0;
    for (const w of words) {
        if (!l[i]) {
            l[i] = w;
            continue;
        }
        if (`${l[i]} ${w}`.length <= n) l[i] += ` ${w}`;
        else if (i === 0) {
            i = 1;
            l[1] = w;
        } else {
            const cut = `${l[1]} ${w}`;
            l[1] = cut.length > n - 3 ? `${cut.slice(0, n - 3).replace(/\s+\S*$/, '')}...` : cut;
            break;
        }
    }
    for (let k = 0; k < 2; k++) if (l[k]!.length > n) l[k] = `${l[k]!.slice(0, Math.max(0, n - 3))}...`;
    return l;
}

export function countText(n: number | null): string {
    if (n === null) return '';
    return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function headText(lay: Layout, w: { num: string; tag: string; name: string; kind: string; dl: string; brief: string }): string {
    const f = lay.f;
    return lay.t === 'wide' ? `${pad(w.num, f.num, true)} ${pad(w.tag, f.tag)} ${pad(w.name, f.name)} ${pad(w.kind, f.kind)} ${pad(w.dl, f.dl, true)} ${w.brief}` : '';
}

export function rowLines(r: RowInput, i: number, lay: Layout): Seg[][] {
    const f = lay.f;
    const dm = (s: string): Seg => ({ c: 'dm', s });
    const num = pad(String(i + 1), 2, true);
    const box: Seg = { c: 'fa-bx', s: r.tagged ? '[x]' : '[ ]' };
    const kt: Seg = { c: 'k-tag', s: r.kindTag, kind: r.kind };
    const mk = r.mark;
    const markOn1 = !!mk && r.name.length + 1 + mk.length <= f.name;
    const markOn2 = !!mk && !markOn1;
    const nm = r.name.length > f.name ? fit(r.name, f.name) : r.name;
    const nmCell: Seg[] = [{ c: 'nm', s: nm }, ...(markOn1 ? [{ c: 'mk', s: ` ${mk}` }] : []), { c: '', s: ' '.repeat(Math.max(0, f.name - nm.length - (markOn1 ? mk.length + 1 : 0))) }];
    const count = countText(r.dl);
    if (lay.t === 'wide') {
        const bl = wrap2(r.brief, f.brief);
        return [
            [dm(`${num} `), box, { c: '', s: ' ' }, ...nmCell, { c: '', s: ' ' }, kt, dm(` ${pad(count, f.dl, true)} `), { c: 'br', s: bl[0] }],
            [dm(pad('', 7)), ...(markOn2 ? [{ c: 'mk', s: mk }] : []), dm(pad('', Math.max(0, f.name - (markOn2 ? mk.length : 0)) + 13)), { c: 'br', s: bl[1] }],
        ];
    }
    return [
        [dm(`${num} `), box, { c: '', s: ' ' }, ...nmCell, { c: '', s: ' ' }, kt, dm(` ${pad(count, 4, true)}`)],
        [dm(pad('', 7)), ...(markOn2 ? [{ c: 'mk', s: `${mk} ` }] : []), { c: 'br', s: fit(r.brief, f.brief - (markOn2 ? mk.length + 1 : 0)) }],
    ];
}

export function sizeText(n: number): string {
    return n >= 1048576 ? `${(n / 1048576).toFixed(1)}M` : n >= 1024 ? `${(n / 1024).toFixed(n >= 10240 ? 0 : 1)}k` : `${n}B`;
}

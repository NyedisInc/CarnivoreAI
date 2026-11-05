
from __future__ import annotations

import base64
import re
import zlib
from typing import Callable, Dict

JS = b"app.alert('pwned');"
HDR = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
PAGES = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"
CAT_HIDDEN = b"<< /Type /Catalog /Pages 2 0 R /Names 4 0 R /OpenAction 6 0 R >>"
HIDDEN = {4: b"<< /JavaScript 5 0 R >>", 5: b"<< /Names [(a) 6 0 R] >>", 6: b"<< /S /JavaScript /JS (" + JS + b") >>"}
BASE = {1: CAT_HIDDEN, 2: PAGES, 3: PAGE}
CLEAN_CAT = b"<< /Type /Catalog /Pages 2 0 R /OpenAction [3 0 R /Fit] >>"


def classic(objs: Dict[int, bytes], prelude: bytes = b"") -> bytes:
    out, offs = bytearray(HDR + prelude), {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    size, xref = max(objs) + 1, len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for n in range(1, size):
        out += (b"%010d 00000 n \n" % offs[n]) if n in offs else b"0000000000 65535 f \n"
    return bytes(out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref))


def stm(extra: bytes, encoded: bytes, kw: bytes = b"stream\n") -> bytes:
    return b"<< %s /Length %d >>\n" % (extra, len(encoded)) + kw + encoded + b"\nendstream"


def with_objstm(plain: Dict[int, bytes], inner: Dict[int, bytes], make: Callable[[bytes, bytes], bytes], stm_num: int = 7) -> bytes:
    nums, header, bodies, off = sorted(inner), [], [], 0
    for n in nums:
        header.append(b"%d %d" % (n, off))
        bodies.append(inner[n] + b"\n")
        off += len(inner[n]) + 1
    head, out, offs = b" ".join(header) + b"\n", bytearray(HDR), {}
    for n in sorted(plain):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + plain[n] + b"\nendobj\n"
    offs[stm_num] = len(out)
    out += b"%d 0 obj\n" % stm_num + make(head, b"".join(bodies)) + b"\nendobj\n"
    xnum = max(list(plain) + nums + [stm_num]) + 1
    offs[xnum], rows = len(out), bytearray()
    for n in range(xnum + 1):
        if n in nums:
            rows += bytes([2]) + stm_num.to_bytes(3, "big") + nums.index(n).to_bytes(2, "big")
        elif n in offs:
            rows += bytes([1]) + offs[n].to_bytes(3, "big") + (0).to_bytes(2, "big")
        else:
            rows += bytes([0, 0, 0, 0, 0xFF, 0xFF])
    out += b"%d 0 obj\n<< /Type /XRef /Size %d /W [1 3 2] /Root 1 0 R /Length %d >>\nstream\n" % (xnum, xnum + 1, len(rows)) + bytes(rows)
    return bytes(out + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % offs[xnum])


def objstm_maker(extra: bytes, encode: Callable[[bytes], bytes], kw: bytes = b"stream\n") -> Callable[[bytes, bytes], bytes]:
    def make(head: bytes, content: bytes) -> bytes:
        return stm(b"/N %d /First %d " % (len(re.findall(rb"\d+ \d+", head)), len(head)) + extra, encode(head + content), kw)
    return make


def a85_maker(head: bytes, content: bytes) -> bytes:
    head += b" " * (-len(head) % 4)
    n = len(re.findall(rb"\d+ \d+", head))
    enc = base64.a85encode(head) + b"endstream!" + base64.a85encode(content) + b"~>"
    return stm(b"/Type /ObjStm /N %d /First %d /Filter /ASCII85Decode" % (n, len(head) + 8), enc)


def png_none(data: bytes, cols: int = 4) -> bytes:
    data += b" " * (-len(data) % cols)
    return zlib.compress(b"".join(b"\x00" + data[i:i + cols] for i in range(0, len(data), cols)))


def objstm(extra: bytes, encode: Callable[[bytes], bytes] = zlib.compress, kw: bytes = b"stream\n", inner: Dict[int, bytes] = HIDDEN) -> bytes:
    return with_objstm(BASE, inner, objstm_maker(extra, encode, kw))


def flate2(d: bytes) -> bytes:
    return zlib.compress(zlib.compress(d))


ACT = b"<< /S /JavaScript /JS (" + JS + b") >>"
NAMES_ACT = {4: b"<< /JavaScript 5 0 R >>", 5: b"<< /Names [(a) 6 0 R] >>", 6: ACT}
CAT = b"<< /Type /Catalog /Pages 2 0 R /Names 4 0 R /OpenAction 6 0 R >>"


class Writer:

    def __init__(self) -> None:
        self.buf, self.offs = bytearray(HDR), {}

    def obj(self, n: int, body: bytes) -> None:
        self.offs[n] = len(self.buf)
        self.buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"

    def finish(self, root: int = 1) -> bytes:
        size, xref = max(self.offs) + 1, len(self.buf)
        self.buf += b"xref\n0 %d\n0000000000 65535 f \n" % size
        for n in range(1, size):
            self.buf += (b"%010d 00000 n \n" % self.offs[n]) if n in self.offs else b"0000000000 65535 f \n"
        self.buf += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, root, xref)
        return bytes(self.buf)


def _inner_objects(header: bytes = b"%d 0 obj") -> tuple:
    inner, rel = bytearray(), {}
    for n, body in NAMES_ACT.items():
        rel[n] = len(inner)
        inner += header % n + b"\n" + body + b"\nendobj\n"
    return bytes(inner), rel


def hidden_in_body(carrier_dict: bytes, extra: bytes = b"", header: bytes = b"%d 0 obj") -> bytes:
    w = Writer()
    w.obj(1, CAT), w.obj(2, PAGES), w.obj(3, PAGE if not extra else extra)
    inner, rel = _inner_objects(header)
    head = b"7 0 obj\n<< %s /Length %d >>\nstream\n" % (carrier_dict, len(inner))
    base = len(w.buf) + len(head)
    w.offs[7] = len(w.buf)
    w.buf += head + inner + b"\nendstream\nendobj\n"
    w.offs.update({n: base + r for n, r in rel.items()})
    return w.finish()


def hidden_objstm_in_body() -> bytes:
    o = {n: NAMES_ACT[n] + b"\n" for n in (4, 5, 6)}
    hd = b"4 0 5 %d 6 %d\n" % (len(o[4]), len(o[4]) + len(o[5]))
    comp = zlib.compress(hd + o[4] + o[5] + o[6])
    nested = b"8 0 obj\n<< /Type /ObjStm /N 3 /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (len(hd), len(comp)) + comp + b"\nendstream\nendobj\n"
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CAT), (2, PAGES), (3, PAGE)):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    carrier = b"7 0 obj\n<< /Length %d >>\nstream\n" % len(nested)
    offs[7], offs[8] = len(buf), len(buf) + len(carrier)
    buf += carrier + nested + b"\nendstream\nendobj\n"
    offs[9], rows = len(buf), bytearray()
    for n in range(10):
        rows += (bytes([2]) + (8).to_bytes(3, "big") + (n - 4).to_bytes(2, "big")) if n in (4, 5, 6) else (
            bytes([1]) + offs[n].to_bytes(3, "big") + b"\0\0" if n in offs else bytes([0, 0, 0, 0, 0xFF, 0xFF]))
    buf += b"9 0 obj\n<< /Type /XRef /Size 10 /W [1 3 2] /Root 1 0 R /Length %d >>\nstream\n" % len(rows) + rows + b"\nendstream\nendobj\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % offs[9])


def hidden_xref_and_catalog() -> bytes:
    w = Writer()
    w.obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"), w.obj(2, PAGES), w.obj(3, PAGE)
    carrier = len(w.buf)
    pre = b"7 0 obj\n<< /Length %010d >>\nstream\n"
    base, inner, offs = carrier + len(pre % 0), bytearray(), {2: w.offs[2], 3: w.offs[3], 7: carrier}
    for n, body in ((10, CAT), *NAMES_ACT.items()):
        offs[n] = base + len(inner)
        inner += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    at = base + len(inner)
    inner += b"xref\n0 11\n0000000000 65535 f \n"
    for n in range(1, 11):
        inner += (b"%010d 00000 n \n" % offs[n]) if n in offs else b"0000000000 65535 f \n"
    inner += b"trailer\n<< /Size 11 /Root 10 0 R >>\n"
    w.buf += pre % len(inner) + bytes(inner) + b"\nendstream\nendobj\n"
    return bytes(w.buf) + b"startxref\n%d\n%%%%EOF\n" % at


def three_d_on_instantiate() -> bytes:
    js = b"host.app.alert('pwned');"
    w = Writer()
    w.obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"), w.obj(2, PAGES)
    w.obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Annots [8 0 R] >>")
    w.obj(7, b"<< /Length %d >>\nstream\n" % len(js) + js + b"\nendstream")
    w.obj(9, b"<< /Type /3D /Subtype /U3D /OnInstantiate 7 0 R /Length 4 >>\nstream\nU3D\0\nendstream")
    w.obj(8, b"<< /Type /Annot /Subtype /3D /Rect [0 0 200 200] /3DD 9 0 R /3DA << /A /PO /D /PC >> >>")
    return w.finish()


def dup_action_key() -> bytes:
    w = Writer()
    w.obj(1, b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /GoToR /F (\\\\\\\\10.0.0.6\\\\s\\\\x.pdf) /D [0 /Fit] /S /GoTo /D [3 0 R /Fit] >> >>")
    w.obj(2, PAGES), w.obj(3, PAGE)
    return w.finish()


CAT_NAMES4 = b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>"
CAT_NAMES6 = b"<< /Type /Catalog /Pages 2 0 R /OpenAction 6 0 R >>"
IMG7 = b"<< /Type /XObject /Subtype /Image /Width 1 /Height %d /BitsPerComponent 8 /ColorSpace /DeviceGray /Length %d >>\nstream\n"
_IMG_CARRIER = b"/Type /XObject /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 8 /ColorSpace /DeviceGray"


def _image_body_cases(prefix: bytes, after_obj: bytes) -> bytes:
    w = Writer()
    w.obj(1, CAT), w.obj(2, PAGES)
    w.obj(3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /XObject << /Im1 7 0 R >> >> >>")
    inner, rel = bytearray(), {}
    for n in (4, 5, 6):
        inner += prefix
        rel[n] = len(inner)
        inner += b"%d 0 obj" % n + after_obj + NAMES_ACT[n] + b"\nendobj\n"
    head = IMG7 % (len(inner), len(inner))
    base = len(w.buf) + len(head)
    w.offs[7] = len(w.buf)
    w.buf += b"7 0 obj\n" + head + bytes(inner) + b"\nendstream\nendobj\n"
    w.offs.update({n: base + r for n, r in rel.items()})
    return w.finish()


def _png_up(rows_payload: bytes, columns: int) -> bytes:
    prev, out = bytes(columns), bytearray()
    for i in range(0, len(rows_payload), columns):
        row = rows_payload[i:i + columns].ljust(columns, b"\x00")
        out += b"\x02" + bytes((row[j] - prev[j]) & 0xFF for j in range(columns))
        prev = row
    return zlib.compress(bytes(out))


def _xref_stream_rows(offs: Dict[int, int], size: int, body_obj: int, body_at: int) -> bytes:
    rows = bytearray()
    for n in range(size):
        if n == body_obj:
            rows += bytes([1]) + body_at.to_bytes(4, "big") + (0).to_bytes(2, "big")
        elif n in offs:
            rows += bytes([1]) + offs[n].to_bytes(4, "big") + (0).to_bytes(2, "big")
        else:
            rows += bytes([0]) + (0).to_bytes(4, "big") + (0xFFFF).to_bytes(2, "big")
    return bytes(rows)


def xref_stream_into_body(predictor: bool) -> bytes:
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CAT_NAMES4), (2, PAGES), (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /XObject << /Im1 7 0 R >> >> >>")):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    inner = b"4 0 obj\n" + ACT + b"\nendobj\n"
    head = IMG7 % (len(inner), len(inner))
    offs[7], body4 = len(buf), len(buf) + len(b"7 0 obj\n") + len(head)
    buf += b"7 0 obj\n" + head + inner + b"\nendstream\nendobj\n"
    offs[4] = body4
    xnum, size = 8, 9
    offs[xnum] = len(buf)
    rows = _xref_stream_rows(offs, size, 4, body4)
    if predictor:
        enc = _png_up(rows, 7)
        dic = b"<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 7 >> /Length %d >>" % (size, len(enc))
    else:
        enc = zlib.compress(rows)
        dic = b"<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Filter /FlateDecode /Length %d >>" % (size, len(enc))
    buf += b"%d 0 obj\n" % xnum + dic + b"\nstream\n" + enc + b"\nendstream\nendobj\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % offs[xnum])


def prev_chain_into_body() -> bytes:
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CAT_NAMES4), (2, PAGES), (3, PAGE)):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    base = len(buf)
    buf += b"xref\n0 5\n0000000000 65535 f \n"
    for n in range(1, 5):
        buf += (b"%010d 00000 n \n" % offs[n]) if n in offs else b"0000000000 65535 f \n"
    buf += b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % base
    inner = b"4 0 obj\n" + ACT + b"\nendobj\n"
    carrier = b"9 0 obj\n<< /Length %d >>\nstream\n" % len(inner)
    offs[9], body4 = len(buf), len(buf) + len(carrier)
    buf += carrier + inner + b"\nendstream\nendobj\n"
    upd = len(buf)
    buf += b"xref\n0 1\n0000000000 65535 f \n4 1\n%010d 00000 n \n9 1\n%010d 00000 n \n" % (body4, offs[9])
    return bytes(buf + b"trailer\n<< /Size 10 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (base, upd))


def type2_hidden_objstm() -> bytes:
    objstm_hd = b"6 0\n"
    comp = zlib.compress(objstm_hd + ACT + b"\n")
    nested = b"8 0 obj\n<< /Type /ObjStm /N 1 /First %d /Filter /FlateDecode /Length %d >>\nstream\n" % (len(objstm_hd), len(comp)) + comp + b"\nendstream\nendobj\n"
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CAT_NAMES6), (2, PAGES), (3, PAGE)):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    carrier = b"7 0 obj\n<< /Length %d >>\nstream\n" % len(nested)
    offs[7], offs[8] = len(buf), len(buf) + len(carrier)
    buf += carrier + nested + b"\nendstream\nendobj\n"
    xnum, size = 9, 10
    offs[xnum], rows = len(buf), bytearray()
    for n in range(size):
        if n == 6:
            rows += bytes([2]) + (8).to_bytes(4, "big") + (0).to_bytes(2, "big")
        elif n in offs:
            rows += bytes([1]) + offs[n].to_bytes(4, "big") + (0).to_bytes(2, "big")
        else:
            rows += bytes([0]) + (0).to_bytes(4, "big") + (0xFFFF).to_bytes(2, "big")
    enc = zlib.compress(bytes(rows))
    dic = b"<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Filter /FlateDecode /Length %d >>" % (size, len(enc))
    buf += b"%d 0 obj\n" % xnum + dic + b"\nstream\n" + enc + b"\nendstream\nendobj\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % offs[xnum])


def deep_prev_chain(sections: int) -> bytes:
    buf, offs = bytearray(HDR), {}
    for num, body in ((1, CLEAN_CAT), (2, PAGES), (3, PAGE)):
        offs[num] = len(buf)
        buf += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    base = len(buf)
    buf += b"xref\n0 4\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % offs[n] for n in range(1, 4))
    buf += b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % base
    prev = base
    for _ in range(sections):
        here = len(buf)
        buf += b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 4 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (prev, here)
        prev = here
    return bytes(buf)


def unparseable_chained_section() -> bytes:
    buf, offs = bytearray(HDR), {}
    for num, body in ((1, CLEAN_CAT), (2, PAGES), (3, PAGE)):
        offs[num] = len(buf)
        buf += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    garbage_at = len(buf)
    buf += b"this is not a cross reference at all, just bytes\n"
    base = len(buf)
    buf += b"xref\n0 4\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % offs[n] for n in range(1, 4))
    return bytes(buf + b"trailer\n<< /Size 4 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (garbage_at, base))


def broken_primary_xref() -> bytes:
    buf, offs = bytearray(HDR), {}
    for num, body in ((1, CLEAN_CAT), (2, PAGES), (3, PAGE)):
        offs[num] = len(buf)
        buf += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    bogus = len(buf)
    buf += b"xxxxxxx not an xref here xxxxxxx\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % bogus)


def ordinary_xref_stream_predictor() -> bytes:
    buf, offs = bytearray(HDR), {}
    for n, body in ((1, CLEAN_CAT), (2, PAGES), (3, PAGE)):
        offs[n] = len(buf)
        buf += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xnum, size = 4, 5
    offs[xnum] = len(buf)
    rows = _xref_stream_rows(offs, size, -1, 0)
    enc = _png_up(rows, 7)
    dic = b"<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 7 >> /Length %d >>" % (size, len(enc))
    buf += b"%d 0 obj\n" % xnum + dic + b"\nstream\n" + enc + b"\nendstream\nendobj\n"
    return bytes(buf + b"startxref\n%d\n%%%%EOF\n" % offs[xnum])


T = b"/Type /ObjStm /Filter /FlateDecode"
def gap_backtrack(n: int) -> bytes:
    w = Writer()
    w.obj(1, CAT), w.obj(2, PAGES), w.obj(3, PAGE)
    inner = b"1 " + b"%" * n + b"\nX"
    head = b"7 0 obj\n<< %s /Length %d >>\nstream\n" % (_IMG_CARRIER.replace(b"/Height 1", b"/Height %d" % len(inner)), len(inner))
    base = len(w.buf) + len(head)
    w.offs[7] = len(w.buf)
    w.buf += head + inner + b"\nendstream\nendobj\n"
    w.offs[8] = base
    return w.finish()


BYPASSES: Dict[str, Callable[[], bytes]] = {
    "plain_js": lambda: classic({**BASE, **HIDDEN}),
    "comment_fake_stream": lambda: classic({**BASE, **HIDDEN, 7: stm(b"", b"")}, prelude=b"%stream\n"),
    "string_fake_stream": lambda: classic({1: CAT_HIDDEN[:-2] + b"/Lang (stream\n) >>", 2: PAGES, 3: PAGE, **HIDDEN, 7: stm(b"", b"")}),
    "nul_delimiter": lambda: classic({**BASE, 4: b"<< /JavaScript\x00 5 0 R >>", 5: HIDDEN[5], 6: b"<< /S /JavaScript\x00/JS\x00(" + JS + b") >>"}),
    "objstm_flate": lambda: objstm(T),
    "objstm_space_before_eol": lambda: objstm(T, kw=b"stream \n"),
    "objstm_no_type": lambda: objstm(b"/Filter /FlateDecode"),
    "objstm_string_moves_cut": lambda: objstm(T + b" /X (9 0 obj)"),
    "objstm_decoy_filter_in_parms": lambda: objstm(b"/Type /ObjStm /DecodeParms [<< /X /Filter /FlateDecode 1 >> null] /Filter [/FlateDecode /FlateDecode]", flate2),
    "objstm_comment_in_filter_array": lambda: objstm(b"/Type /ObjStm /Filter [/FlateDecode %]\n /FlateDecode]", flate2),
    "objstm_a85_endstream_inside": lambda: with_objstm(BASE, HIDDEN, a85_maker),
    "objstm_predictor_plus_sign": lambda: objstm(T + b" /DecodeParms << /Predictor +10 /Columns 4 >>", png_none),
    "objstm_lzw": lambda: objstm(b"/Type /ObjStm /Filter /LZWDecode", lambda d: d),
    "hex_escaped_name": lambda: classic({**BASE, 6: b"<< /S /J#61vaScr#69pt /JS (x) >>"}),
    "objstm_hex_filter": lambda: objstm(b"/Type /ObjStm /Filter /ASCIIHexDecode", lambda d: base64.b16encode(d) + b">"),
    "duplicate_filter_key": lambda: objstm(T + b" /Filter /LZWDecode"),
    "hidden_in_stream_body": lambda: hidden_in_body(b""),
    "hidden_gen_six_digits": lambda: hidden_in_body(b"", header=b"%d 000000 obj"),
    "hidden_comment_before_obj": lambda: hidden_in_body(b"", header=b"%d 0 %%c\nobj"),
    "hidden_comment_between_numbers": lambda: hidden_in_body(b"", header=b"%d %%c\n0 obj"),
    "hidden_vtab_separator": lambda: hidden_in_body(b"", header=b"%d\x0b0\x0bobj"),
    "hidden_in_image_stream": lambda: hidden_in_body(b"/Type /XObject /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 8 /ColorSpace /DeviceGray"),
    "hidden_objstm_in_stream_body": hidden_objstm_in_body,
    "hidden_xref_and_catalog": hidden_xref_and_catalog,
    "three_d_on_instantiate": three_d_on_instantiate,
    "dup_action_type_gotor_first": dup_action_key,
    "dup_s_in_action": lambda: classic({**BASE, 6: b"<< /S /GoTo /S /JavaScript /JS (" + JS + b") >>"}),
    "hidden_sliding_one_number": lambda: _image_body_cases(b"9 ", b"\n"),
    "hidden_sliding_three_numbers": lambda: _image_body_cases(b"7 8 9 ", b"\n"),
    "hidden_vtab_after_obj": lambda: _image_body_cases(b"", b"\x0b"),
    "xref_stream_predictor_into_body": lambda: xref_stream_into_body(True),
    "xref_stream_flate_into_body": lambda: xref_stream_into_body(False),
    "xref_prev_chain_into_body": prev_chain_into_body,
    "xref_type2_hidden_objstm": type2_hidden_objstm,
    "hidden_gen_glued_obj": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d 0obj"),
    "hidden_plus_gen": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d+0 obj"),
    "hidden_minus_gen": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d-0 obj"),
    "hidden_plus_gen_glued_obj": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d+0obj"),
    "hidden_leadingzero_glued_obj": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d 00obj"),
    "hidden_obj_glued_to_dict": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d 0obj<<"),
    "hidden_mixed_ws_then_glued_obj": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d \t\r\n0obj"),
    "hidden_leading_comment_at_offset": lambda: hidden_in_body(_IMG_CARRIER, header=b"%%c leading comment\n%d 0 obj"),
    "hidden_lone_plus_gen_spaced": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d + obj"),
    "hidden_lone_plus_gen_glued": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d +obj"),
    "hidden_lone_minus_gen_spaced": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d - obj"),
    "hidden_lone_minus_gen_glued": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d -obj"),
    "hidden_number_then_plus_obj": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d+obj"),
    "hidden_number_60_leading_zeros": lambda: hidden_in_body(_IMG_CARRIER, header=b"0" * 60 + b"%d 0 obj"),
    "hidden_gen_60_zeros": lambda: hidden_in_body(_IMG_CARRIER, header=b"%d " + b"0" * 60 + b" obj"),
}

ROUND9_REVIEW = ["hidden_lone_plus_gen_spaced", "hidden_lone_plus_gen_glued", "hidden_lone_minus_gen_spaced", "hidden_lone_minus_gen_glued",
                 "hidden_number_then_plus_obj", "hidden_number_60_leading_zeros", "hidden_gen_60_zeros"]

ORDINARY: Dict[str, Callable[[], bytes]] = {
    "classic": lambda: classic({1: CLEAN_CAT, 2: PAGES, 3: PAGE}),
    "classic_link_annotation": lambda: classic({1: CLEAN_CAT, 2: PAGES, 3: b"<< /Type /Page /Parent 2 0 R /Annots [<< /Subtype /Link /A << /S /URI /URI (http://example.com) >> >>] >>"}),
    "objstm_flate": lambda: objstm(T, inner={1: CLEAN_CAT, 2: PAGES, 3: PAGE}),
    "objstm_no_type_two_layers": lambda: objstm(b"/Filter [/FlateDecode /FlateDecode]", flate2, inner={4: PAGE, 5: b"<< /Type /Font >>"}),
    "length_in_later_object": lambda: classic({1: CLEAN_CAT, 2: PAGES, 3: PAGE, 4: stm(b"", b"BT ET").replace(b"/Length 5", b"/Length 5 0 R"), 5: b"5"}),
    "body_holds_endstream_bytes": lambda: classic({1: CLEAN_CAT, 2: PAGES, 3: PAGE, 4: stm(b"", b"junk endstream junk\n(")}),
    "length_in_object_stream": lambda: with_objstm({1: CLEAN_CAT, 2: PAGES, 3: PAGE, 4: stm(b"", b"BT ET").replace(b"/Length 5", b"/Length 5 0 R")},
                                                   {5: b"5"}, objstm_maker(T, zlib.compress)),
    "escaped_parens_and_signed_numbers": lambda: classic({1: CLEAN_CAT, 2: PAGES, 3: b"<< /Type /Page /Parent 2 0 R /Note (a\\) b \\\\ (nested) c) /Rect [-5 +3 -.5 0] >>"}),
    "goto_open_action_chain": lambda: classic({1: b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>", 2: PAGES, 3: PAGE, 4: b"<< /S /GoTo /D [3 0 R /Fit] /Next 5 0 R >>", 5: b"<< /S /GoTo /D [3 0 R /XYZ 0 0 0] >>"}),
    "xref_stream_with_png_predictor": ordinary_xref_stream_predictor,
}

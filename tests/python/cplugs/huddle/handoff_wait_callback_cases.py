import http.server, importlib.machinery, importlib.util, json, os, sys, tempfile, threading, unittest

HOME = tempfile.mkdtemp()
os.environ["HANDOFF_HOME"] = HOME
for d in ("pending", "done", "archive", "log"):
    os.makedirs(os.path.join(HOME, d))
loader = importlib.machinery.SourceFileLoader("handoff", sys.argv.pop(1))
hf = importlib.util.module_from_spec(importlib.util.spec_from_loader("handoff", loader))
sys.modules["handoff"] = hf
loader.exec_module(hf)

TOKEN = "tok_" + "b5a9f4e3" * 4


class Fake(http.server.BaseHTTPRequestHandler):
    seen, reply = [], 200

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Fake.seen.append((self.path, json.loads(body), dict(self.headers)))
        self.send_response(Fake.reply)
        self.end_headers()

    def log_message(self, *args):
        pass


def put_script(name, steps, header=True):
    lines = ["# handoff: wait test", "# why: proves the callback"]
    if header:
        lines.append("# carnivore-wait: 42 " + TOKEN)
    lines += ['step "step %d" -- %s' % (i + 1, cmd) for i, cmd in enumerate(steps)]
    path = os.path.join(HOME, "pending", name + ".sh")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def run_script(path, answers, out):
    sc = hf.load_script(path)
    assert not sc.error, sc.error
    run = hf.Run(sc, False, lambda text, kind: out.append(text), "handoff")
    run.begin()
    for i, it in enumerate(sc.items):
        if it.kind != "step":
            continue
        if answers[i] == "y":
            run.execute(i, lambda item, out_path: 0 if item.cmd.strip() == "true" else 3, False)
        else:
            run.skip(i)
    run.finish()
    return run


class WaitCallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        hf.WAIT_URL = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Fake.seen, Fake.reply = [], 200

    def result_text(self, base):
        with open(os.path.join(HOME, "log", base + ".result")) as fh:
            return fh.read()

    def test_every_step_ok_calls_cleared_with_the_token_in_the_body_only(self):
        out = []
        run_script(put_script("ok", ["true", "true"]), ["y", "y"], out)
        path, body, headers = Fake.seen[0]
        self.assertEqual(path, "/api/v1/cplugs/huddle/items/42/wait/resolve")
        self.assertEqual((body["result"], body["token"]), ("cleared", TOKEN))
        self.assertNotIn(TOKEN, repr(headers) + path)
        self.assertTrue(self.result_text("ok").rstrip().endswith("wait-callback: item 42 cleared -> HTTP 200"))
        self.assertNotIn(TOKEN, self.result_text("ok") + "\n".join(out) + open(os.path.join(HOME, "log", "ok.log")).read())

    def test_the_first_failing_step_is_the_reason(self):
        run_script(put_script("bad", ["true", "false", "true"]), ["y", "y", "y"], [])
        body = Fake.seen[0][1]
        self.assertEqual(body["result"], "failed")
        self.assertIn("step 2 failed (exit 3)", body["reason"])

    def test_a_skipped_step_is_a_failure_too(self):
        run_script(put_script("skip", ["true", "true"]), ["y", "n"], [])
        self.assertEqual((Fake.seen[0][1]["result"], Fake.seen[0][1]["reason"].split(":")[0]), ("failed", "step 2 skipped"))

    def test_a_quit_run_and_a_script_without_the_header_call_nothing(self):
        run_script(put_script("plain", ["true"], header=False), ["y"], [])
        self.assertEqual(Fake.seen, [])
        sc = hf.load_script(put_script("quit", ["true", "true"]))
        run = hf.Run(sc, False, lambda t, k: None, "handoff")
        run.begin()
        run.quit(0)
        run.finish()
        self.assertEqual(Fake.seen, [])

    def test_a_dead_server_or_a_refusal_never_fails_the_handoff_and_leaves_one_line(self):
        Fake.reply = 403
        run_script(put_script("refused", ["true"]), ["y"], [])
        self.assertIn("refused, HTTP 403", self.result_text("refused"))
        saved = hf.WAIT_URL
        hf.WAIT_URL = "http://127.0.0.1:1"
        try:
            run = run_script(put_script("down", ["true"]), ["y"], [])
        finally:
            hf.WAIT_URL = saved
        self.assertIn("not delivered", self.result_text("down"))
        self.assertTrue(run.done_path)

    def test_a_half_spoken_reply_never_fails_the_handoff_and_the_result_is_written_first(self):
        class Garbage(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.wfile.write(b"NOT HTTP AT ALL\r\n\r\n")

            def log_message(self, *args):
                pass

        bad = http.server.HTTPServer(("127.0.0.1", 0), Garbage)
        threading.Thread(target=bad.serve_forever, daemon=True).start()
        saved = hf.WAIT_URL
        hf.WAIT_URL = "http://127.0.0.1:%d" % bad.server_address[1]
        try:
            run = run_script(put_script("garbage", ["true"]), ["y"], [])
        finally:
            hf.WAIT_URL = saved
            bad.shutdown()
        text = self.result_text("garbage")
        self.assertTrue(text.index("result: complete") < text.index("wait-callback:"))
        self.assertIn("not delivered", text)
        self.assertTrue(run.done_path)

    def test_a_non_loopback_url_is_refused_and_nothing_is_sent(self):
        saved = hf.WAIT_URL
        try:
            for url in ("https://example.com", "http://203.0.113.11:8000", "ftp://127.0.0.1/x", "http://localhost.example.net"):
                hf.WAIT_URL = url
                self.assertIn("not a loopback address", hf.wait_callback(42, TOKEN, "cleared", ""))
            hf.WAIT_URL = "http://[::1]:1"
            self.assertNotIn("not a loopback", hf.wait_callback(42, TOKEN, "cleared", ""))
        finally:
            hf.WAIT_URL = saved
        self.assertEqual(Fake.seen, [])

    def test_a_malformed_header_is_ignored(self):
        path = put_script("odd", ["true"], header=False)
        with open(path, "a") as fh:
            fh.write("# carnivore-wait: 42 short\n")
        self.assertIsNone(hf.wait_header(path))


if __name__ == "__main__":
    unittest.main()

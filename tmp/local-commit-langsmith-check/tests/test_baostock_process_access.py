"""Real Web/MCP processes against a local fake provider; no external requests."""
import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKER = r'''
import json,os,socket,sys,time
from pathlib import Path
from types import SimpleNamespace
import baostock as bs
import baostock.common.context as context
def result(code="0",rows=()):
    iterator=iter(rows); current=[]
    def advance():
        nonlocal current
        current=next(iterator,None)
        return current is not None
    return SimpleNamespace(error_code=code,error_msg="local fake provider",fields=["value"],next=advance,get_row_data=lambda:current)
def exchange(message):
    context.default_socket.sendall(message+b"\n")
    data=b""
    while not data.endswith(b"\n"): data+=context.default_socket.recv(256)
    return data.strip().decode()
def login():
    context.default_socket=socket.create_connection(("127.0.0.1",int(sys.argv[2])),timeout=5)
    return result(exchange(b"login"))
def logout():
    return result(exchange(b"logout"))
def query():
    print("SDK query diagnostic")
    assert exchange(b"query")=="0"
    return result(rows=[["preserved"]])
bs.login=login; bs.logout=logout
if sys.argv[1]=="web":
    sys.path.insert(0,str(Path.cwd()/"agents"))
    from src.utils.baostock_helper import safe_query
    def run():
        cursor=safe_query(query)
        assert cursor.next() and cursor.get_row_data()==["preserved"]
else:
    sys.path.insert(0,str(Path.cwd()/"mcp-server"))
    from src.utils import fetch_generic_data
    def run():
        assert fetch_generic_data(query,"local test").iloc[0,0]=="preserved"
print("READY",flush=True)
deadline=time.monotonic()+10
while not Path(sys.argv[3]).exists():
    if time.monotonic()>deadline: raise RuntimeError("gate timeout")
    time.sleep(.01)
run()
print("DONE",flush=True)
'''


class ProcessAccessTests(unittest.TestCase):
    def test_web_and_mcp_never_hold_provider_connections_at_the_same_time(self):
        state = {"active": 0, "maximum": 0, "rejections": 0}
        lock = threading.Lock()

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                owned = False
                try:
                    for line in self.rfile:
                        if line.strip() == b"login":
                            with lock:
                                if state["active"]:
                                    state["rejections"] += 1
                                    code = b"10001011\n"
                                else:
                                    state["active"] += 1
                                    state["maximum"] = max(state["maximum"], state["active"])
                                    owned = True
                                    code = b"0\n"
                            self.wfile.write(code)
                        elif line.strip() == b"query":
                            # Keep a login alive long enough to expose overlapping
                            # connections in independently scheduled processes.
                            time.sleep(.3)
                            self.wfile.write(b"0\n")
                        elif line.strip() == b"logout":
                            with lock:
                                if owned: state["active"] -= 1
                                owned = False
                            self.wfile.write(b"0\n")
                finally:
                    if owned:
                        with lock: state["active"] -= 1

        with tempfile.TemporaryDirectory() as temporary, socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as provider:
            provider.daemon_threads = True
            thread = threading.Thread(target=provider.serve_forever, daemon=True)
            thread.start()
            gate = Path(temporary) / "start"
            environment = {**os.environ, "FINEX_BAOSTOCK_STATE_DIR": str(Path(temporary) / "state"), "PYTHONIOENCODING": "utf-8"}
            children = []
            try:
                for entry in ("web", "mcp"):
                    child = subprocess.Popen([sys.executable, "-u", "-c", WORKER, entry, str(provider.server_address[1]), str(gate)],
                                             cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                    children.append(child)
                for child in children:
                    self.assertEqual(child.stdout.readline().strip(), "READY")
                gate.write_text("go", encoding="utf-8")
                outcomes = [child.communicate(timeout=20) for child in children]
                for child, (stdout, stderr) in zip(children, outcomes):
                    self.assertEqual(child.returncode, 0, stderr)
                    self.assertIn("DONE", stdout)
                    self.assertNotIn("SDK query diagnostic", stdout)
                    self.assertIn("SDK query diagnostic", stderr)
                self.assertEqual(state["rejections"], 0)
                self.assertEqual(state["maximum"], 1)
                self.assertEqual(state["active"], 0)
            finally:
                for child in children:
                    if child.poll() is None: child.kill()
                    child.communicate(timeout=5)
                provider.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

import json
import socket
import threading
from pathlib import Path

resultTag = "@@OVEN_RESULT@@"

scriptPostlude = """
try:
    print(resultTag + json.dumps(main(args)))
except Exception:
    import traceback
    raise RuntimeError(traceback.format_exc())
"""


class BlenderError(Exception):
    pass


class BlenderClient:
    def __init__(self, host="localhost", port=9876, timeout=180.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None
        self.lock = threading.Lock()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        if not self.sock:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=10)
            except OSError as e:
                raise BlenderError(f"cannot reach Blender at {self.host}:{self.port} ({e}); is the addon server started?") from e
        return self

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def send(self, cmdType, params=None, timeout=None):
        payload = json.dumps({"type": cmdType, "params": params or {}}).encode()
        with self.lock:
            resp = self._roundTrip(payload, timeout or self.timeout, retry=True)
        if resp.get("status") == "error":
            raise BlenderError(f"{cmdType}: {resp.get('message')}")
        result = resp.get("result")
        if isinstance(result, dict) and (result.get("error") or result.get("succeed") is False):
            raise BlenderError(f"{cmdType}: {result.get('error') or result}")
        if isinstance(result, str) and result.startswith("Error"):
            raise BlenderError(f"{cmdType}: {result}")
        return result

    def _roundTrip(self, payload, timeout, retry):
        self.connect()
        received = False
        try:
            self.sock.settimeout(timeout)
            self.sock.sendall(payload)
            buf = b""
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("Blender closed the connection")
                received = True
                buf += chunk
                try:
                    return json.loads(buf)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
        except TimeoutError as e:
            self.close()
            raise BlenderError(f"no response from Blender within {timeout}s") from e
        except OSError as e:
            self.close()
            if retry and not received:
                return self._roundTrip(payload, timeout, retry=False)
            raise BlenderError(f"connection to Blender lost ({e})") from e

    def ping(self):
        return self.send("ping")

    def addonInfo(self):
        return self.send("get_addon_info")

    def sceneInfo(self):
        return self.send("get_scene_info")

    def objectInfo(self, name):
        return self.send("get_object_info", {"name": name})

    def execCode(self, code, timeout=None):
        return self.send("execute_code", {"code": code}, timeout).get("result", "")

    def runScript(self, path, args=None, timeout=None):
        path = Path(path)
        prelude = f"import json; args = json.loads({json.dumps(json.dumps(args or {}))}); resultTag = {resultTag!r}\n"
        out = self.execCode(prelude + path.read_text(encoding="utf-8") + scriptPostlude, timeout)
        for line in reversed(out.splitlines()):
            if line.startswith(resultTag):
                return json.loads(line[len(resultTag):])
        raise BlenderError(f"{path.name} returned no result; stdout:\n{out[-2000:]}")

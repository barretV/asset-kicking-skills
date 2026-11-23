"""
Queue one ComfyUI API graph and wait for it, printing per-node timing and the files it saved.

  python bin/run_prompt.py <graph.api.json> [--host 127.0.0.1:8188] [--timeout 5400]
Exit code 0 on success, 1 on a node error or timeout.
"""
import argparse
import json
import sys
import time
import urllib.request
import uuid


def call(host, path, data=None):
    req = urllib.request.Request(f"http://{host}{path}", data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph")
    ap.add_argument("--host", default="127.0.0.1:8188")
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args()
    graph = json.load(open(a.graph, encoding="utf-8"))
    try:
        r = call(a.host, "/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    except urllib.error.HTTPError as e:
        print("REJECTED", e.read().decode()[:4000])
        return 1
    pid = r["prompt_id"]
    t0 = time.time()
    print("queued", pid, flush=True)
    while time.time() - t0 < a.timeout:
        time.sleep(10)
        h = call(a.host, f"/history/{pid}")
        if pid not in h:
            continue
        st = h[pid]["status"]
        for m in st.get("messages", []):
            if m[0] in ("execution_error", "execution_interrupted"):
                print("ERROR", json.dumps(m[1])[:4000])
                return 1
        if st.get("completed"):
            print(f"done in {time.time() - t0:.0f} s")
            for nid, out in h[pid]["outputs"].items():
                print(nid, json.dumps(out)[:400])
            return 0
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    sys.exit(main())

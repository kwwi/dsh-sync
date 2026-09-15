#!/usr/bin/env python3
"""Minimal DeepSeek vision client: send a local image + prompt, get text back."""
import base64, json, os, sys, urllib.request, urllib.error, mimetypes

API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"


def load_key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k.strip()
    p = os.path.expanduser("~/.dsh/.credentials.yaml")
    if os.path.exists(p):
        try:
            import yaml
            d = yaml.safe_load(open(p))
        except Exception:
            d = None

        def walk(o):
            if isinstance(o, dict):
                for kk, vv in o.items():
                    if kk == "DEEPSEEK_API_KEY" and isinstance(vv, str):
                        return vv
                    r = walk(vv)
                    if r:
                        return r
            elif isinstance(o, list):
                for vv in o:
                    r = walk(vv)
                    if r:
                        return r
            return None
        got = walk(d)
        if got:
            return got.strip()
    # last resort: the temp file created earlier in this session
    t = "/tmp/.dskey"
    if os.path.exists(t):
        return open(t).read().strip()
    raise SystemExit("no DeepSeek API key found")


def img_data_uri(path):
    mt = mimetypes.guess_type(path)[0] or "image/png"
    if mt == "image/jpg":
        mt = "image/jpeg"
    b = open(path, "rb").read()
    return f"data:{mt};base64,{base64.b64encode(b).decode()}", len(b)


def ask(path, prompt, model=MODEL, max_tokens=16000, temperature=0.0, retries=3,
        thinking="enabled", images=None):
    """Run one vision request. `images` may list extra image paths to include."""
    paths = [path] + list(images or [])
    content = [{"type": "text", "text": prompt}]
    for p in paths:
        uri, _ = img_data_uri(p)
        content.append({"type": "image_url", "image_url": {"url": uri}})
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": content}],
    }
    if thinking == "disabled":
        body["thinking"] = {"type": "disabled"}
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            API, data=data,
            headers={"Authorization": f"Bearer {load_key()}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                out = json.loads(r.read().decode())
            ch = out["choices"][0]
            msg = ch["message"]
            txt = (msg.get("content") or "").strip()
            reason = (msg.get("reasoning_content") or "").strip()
            # a truncated thinking chain can swallow the whole budget
            if not txt and reason:
                txt = ""
            return txt, ch.get("finish_reason"), out.get("usage", {}), reason
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:500]}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        import time
        time.sleep(2 + 3 * attempt)
    raise SystemExit(f"vision call failed after {retries} tries: {last}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("prompt", nargs="?", default="Describe this image.")
    ap.add_argument("--think", default="enabled", choices=["enabled", "disabled"])
    ap.add_argument("--max-tokens", type=int, default=16000)
    a = ap.parse_args()
    txt, fr, usage, reason = ask(a.image, a.prompt, max_tokens=a.max_tokens,
                                 thinking=a.think)
    print(txt if txt else "(no content)")
    print(f"\n--- finish={fr} usage={usage} reasoning_chars={len(reason)} ---",
          file=sys.stderr)

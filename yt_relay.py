#!/usr/bin/env python3
"""
yt_relay.py — 借用 GitHub Actions 的完整外网，下载 YouTube 视频并抽帧，供本地 Agent “看”。

本机（阿里 DSW 容器）对 youtube.com / googlevideo.com 是 DNS 投毒 + IP 段阻断双重封锁，
本地无法直连；但 api.github.com / codeload.github.com 通，GitHub runner 有完整外网。

两种用法
--------
A. 全自动（需要一个 GitHub PAT，scope 至少 actions:write + contents:write）：
     export GH_TOKEN=ghp_xxx
     python3 yt_relay.py run --repo <你>/<仓库> --url <YouTube链接或11位ID> [--frames 12] [--transcribe]

B. 无 token（你在浏览器里手动点 “Run workflow”，本脚本只负责等 + 回取）：
     python3 yt_relay.py fetch --repo <你>/<仓库>
"""
import argparse, io, json, os, sys, tarfile, time, urllib.parse, urllib.request

API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
UA = "yt-relay/1.0"


def _req(url, method="GET", token=None, data=None, accept="application/vnd.github+json"):
    headers = {"User-Agent": UA, "Accept": accept}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode() if data is not None else None
    if body:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=body, headers=headers, method=method)


def dispatch(repo, token, url, frames="12", start="0", duration="0",
             quality="360", transcribe=False):
    """触发 yt-watch workflow。"""
    payload = {"ref": "main",
               "inputs": {"url": url, "frames": str(frames), "start": str(start),
                          "duration": str(duration), "quality": str(quality),
                          "transcribe": "true" if transcribe else "false"}}
    req = _req(f"{API}/repos/{repo}/actions/workflows/yt-watch.yml/dispatches",
               method="POST", token=token, data=payload)
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"  已触发 (HTTP {r.status})")
    return True


def latest_run(repo, token=None, dispatched_after=None):
    """取最近一次 workflow_dispatch 的 run。公开仓库无需 token。"""
    req = _req(f"{API}/repos/{repo}/actions/workflows/yt-watch.yml/runs?event=workflow_dispatch&per_page=5",
               token=token)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    runs = d.get("workflow_runs") or []
    if not runs:
        return None
    if dispatched_after:
        runs = [x for x in runs if x["created_at"] >= dispatched_after] or runs
    return runs[0]


def wait_for_run(repo, token=None, dispatched_after=None, timeout=1800, interval=20):
    """轮询直到 run 结束。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            run = latest_run(repo, token, dispatched_after)
        except Exception as e:
            print(f"  (轮询出错，继续) {e}")
            run = None
        if run:
            st = run["status"]
            if st != last:
                print(f"  状态: {st} / {run.get('conclusion') or '-'}")
                last = st
            if st == "completed":
                print(f"  结论: {run['conclusion']}  →  {run['html_url']}")
                return run
        time.sleep(interval)
    print("  ⚠️ 等待超时，未拿到结论")
    return None


def fetch_results(repo, branch="main", outdir="/mnt/workspace/yt-relay/results"):
    """经 codeload 拉仓库 tar 包，取出 latest/ 下的帧与文本。"""
    url = f"{CODELOAD}/{repo}/tar.gz/refs/heads/{branch}"
    print(f"  拉取 {url}")
    req = _req(url, accept="application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    print(f"  收到 {len(blob)/1024:.0f} KB")

    want = ("latest/frames/", "latest/", )
    os.makedirs(outdir, exist_ok=True)
    got = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/", 1)
            if len(parts) < 2:
                continue
            rel = parts[1]
            if not rel.startswith("latest/"):
                continue
            # 跳过视频/音频本体，只要帧和文本
            if rel.endswith((".mp4", ".webm", ".mkv", ".m4a", ".opus", ".webm")):
                continue
            dest = os.path.join(outdir, rel.replace("latest/", ""))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            f = tf.extractfile(m)
            if f:
                with open(dest, "wb") as w:
                    w.write(f.read())
                got.append(dest)

    frames = sorted(p for p in got if "/frames/" in p and p.lower().endswith((".jpg", ".jpeg", ".png")))
    print(f"  取回文件 {len(got)} 个，其中帧 {len(frames)} 张")
    for p in got:
        print("    -", p)
    return got, frames


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("run", help="触发 + 等待 + 回取（需要 GH_TOKEN）")
    a.add_argument("--repo", required=True, help="owner/repo")
    a.add_argument("--url", required=True)
    a.add_argument("--frames", default="12")
    a.add_argument("--start", default="0")
    a.add_argument("--duration", default="0")
    a.add_argument("--quality", default="360")
    a.add_argument("--transcribe", action="store_true")
    a.add_argument("--out", default="/mnt/workspace/yt-relay/results")

    b = sub.add_parser("fetch", help="只回取最近一次结果（无需 token，公开仓库）")
    b.add_argument("--repo", required=True)
    b.add_argument("--out", default="/mnt/workspace/yt-relay/results")

    args = ap.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if args.cmd == "run":
        if not token:
            print("❌ run 模式需要 GH_TOKEN 环境变量"); sys.exit(1)
        t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 10))
        dispatch(args.repo, token, args.url, args.frames, args.start,
                 args.duration, args.quality, args.transcribe)
        run = wait_for_run(args.repo, token, dispatched_after=t0)
        if not run or run.get("conclusion") != "success":
            print("⚠️ 运行未成功，仍尝试回取已有结果")
        fetch_results(args.repo, outdir=args.out)
    else:
        _, frames = fetch_results(args.repo, outdir=args.out)
        print("\n抽帧完成，可直接交给 vision 分析：")
        for f in frames:
            print("MEDIA:" + f)


if __name__ == "__main__":
    main()

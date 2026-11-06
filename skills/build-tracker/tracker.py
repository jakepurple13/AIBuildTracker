#!/usr/bin/env python3
"""Build tracker: keeps state.json for a live progress page and serves it locally.

Usage:
  tracker.py init "Title" "Task 1" "Task 2:15" ...   # name[:estimate-minutes]; starts server, opens browser
  tracker.py add "Task" [--est MIN]                  # append a pending task
  tracker.py start [ID|NAME]                         # start a task (default: next pending)
  tracker.py done [--note TEXT]                      # finish the running task
  tracker.py next [--note TEXT]                      # done + start next pending
  tracker.py skip ID [--note TEXT]                   # mark a pending task skipped
  tracker.py note TEXT                               # status line under the current task
  tracker.py finish                                  # close out the build
  tracker.py status                                  # print state summary
  tracker.py url                                     # print (and restart if needed) the page URL

All commands take --dir DIR (default: ~/.build-tracker/<cwd folder name>).
"""
import argparse, json, os, shutil, socket, subprocess, sys, time, webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent


def now():
    return time.time()


def default_dir():
    return Path.home() / ".build-tracker" / Path.cwd().name


def load(d):
    p = d / "state.json"
    if not p.exists():
        sys.exit(f"No tracker in {d}. Run: tracker.py init \"Title\" \"Task 1\" ...")
    return json.loads(p.read_text())


def save(d, s):
    s["updated_at"] = now()
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(s, indent=2))
    os.replace(tmp, d / "state.json")  # atomic: the page never reads a half-written file


def parse_task(spec, est=None):
    name = spec
    if est is None and ":" in spec:
        head, tail = spec.rsplit(":", 1)
        try:
            est, name = float(tail), head
        except ValueError:
            pass
    return {"name": name.strip(), "est_min": est, "status": "pending",
            "started_at": None, "ended_at": None, "note": None}


def find(s, key):
    if key is None:
        return None
    if key.isdigit() and 1 <= int(key) <= len(s["tasks"]):
        return s["tasks"][int(key) - 1]
    for t in s["tasks"]:
        if t["name"].lower() == key.lower():
            return t
    sys.exit(f"No task '{key}'. Use a 1-based ID or exact name; see: tracker.py status")


def running(s):
    return next((t for t in s["tasks"] if t["status"] == "running"), None)


def finish_running(s, note):
    t = running(s)
    if t:
        t["status"], t["ended_at"] = "done", now()
        if note:
            t["note"] = note
    return t


def start_task(s, t):
    if t is None:
        t = next((x for x in s["tasks"] if x["status"] == "pending"), None)
        if t is None:
            return None
    finish_running(s, None)
    t["status"], t["started_at"], t["ended_at"] = "running", now(), None
    s["current_note"] = None
    return t


def port_alive(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def ensure_server(d):
    pf = d / "server.port"
    if pf.exists():
        port = int(pf.read_text())
        if port_alive(port):
            return f"http://127.0.0.1:{port}/", False
    port = free_port()
    log = open(d / "server.log", "a")
    subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                      "--directory", str(d)], stdout=log, stderr=log, start_new_session=True)
    pf.write_text(str(port))
    for _ in range(30):
        if port_alive(port):
            break
        time.sleep(0.1)
    return f"http://127.0.0.1:{port}/", True


def fmt(sec):
    sec = int(sec)
    h, m = divmod(sec // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{sec % 60:02d}s"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("title"); p.add_argument("tasks", nargs="*")
    p.add_argument("--no-open", action="store_true")
    p = sub.add_parser("add"); p.add_argument("name"); p.add_argument("--est", type=float)
    p = sub.add_parser("start"); p.add_argument("task", nargs="?")
    for c in ("done", "next"):
        p = sub.add_parser(c); p.add_argument("--note")
    p = sub.add_parser("skip"); p.add_argument("task"); p.add_argument("--note")
    p = sub.add_parser("note"); p.add_argument("text")
    sub.add_parser("finish"); sub.add_parser("status"); sub.add_parser("url")
    a = ap.parse_args()
    d = (a.dir or default_dir()).expanduser().resolve()

    if a.cmd == "init":
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE / "index.html", d / "index.html")
        s = {"title": a.title, "created_at": now(), "finished_at": None,
             "current_note": None, "tasks": [parse_task(x) for x in a.tasks]}
        save(d, s)
        url, _ = ensure_server(d)
        if not a.no_open:
            webbrowser.open(url)
        print(f"Tracker ready: {url}\nState: {d / 'state.json'}\nTasks: {len(s['tasks'])}")
        return

    s = load(d)
    if a.cmd == "add":
        s["tasks"].append(parse_task(a.name, a.est))
        s["finished_at"] = None
        print(f"Added #{len(s['tasks'])}: {s['tasks'][-1]['name']}")
    elif a.cmd == "start":
        t = start_task(s, find(s, a.task))
        print(f"Started: {t['name']}" if t else "No pending tasks.")
    elif a.cmd in ("done", "next"):
        t = finish_running(s, a.note)
        print(f"Done: {t['name']} ({fmt(t['ended_at'] - t['started_at'])})" if t else "Nothing was running.")
        if a.cmd == "next":
            n = start_task(s, None)
            print(f"Started: {n['name']}" if n else "No pending tasks left.")
    elif a.cmd == "skip":
        t = find(s, a.task)
        t["status"], t["note"] = "skipped", a.note or t["note"]
        print(f"Skipped: {t['name']}")
    elif a.cmd == "note":
        s["current_note"] = a.text
        print("Note set.")
    elif a.cmd == "finish":
        finish_running(s, None)
        s["finished_at"] = now()
        left = [t["name"] for t in s["tasks"] if t["status"] == "pending"]
        print("Build finished." + (f" Still pending: {', '.join(left)}" if left else ""))
    elif a.cmd == "url":
        url, restarted = ensure_server(d)
        print(url + ("  (server restarted)" if restarted else ""))
        return
    elif a.cmd == "status":
        for i, t in enumerate(s["tasks"], 1):
            dur = ""
            if t["started_at"]:
                dur = fmt((t["ended_at"] or now()) - t["started_at"])
            print(f"{i:>2}. [{t['status']:<7}] {t['name']} {dur}")
        return
    save(d, s)


if __name__ == "__main__":
    main()

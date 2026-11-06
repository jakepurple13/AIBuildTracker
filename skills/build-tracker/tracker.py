#!/usr/bin/env python3
"""Build tracker: keeps state.json for a live progress page and serves it locally.

Usage:
  tracker.py init "Title" "Task 1" "Task 2:15" ...   # name[:estimate-minutes]; starts server, opens browser
  tracker.py add "Task" [--est MIN]                  # append a pending task
  tracker.py start [ID|NAME ...]                     # start tasks (default: next pending); others keep running
  tracker.py done [ID|NAME ...] [--note TEXT]        # finish tasks (default: the only running one)
  tracker.py next [ID|NAME] [--note TEXT]            # done + start the next pending task
  tracker.py skip ID [--note TEXT]                   # mark a pending task skipped
  tracker.py note TEXT [--task ID]                   # live status line under a running task
  tracker.py workers N                               # how many tasks run at once (for the ETA)
  tracker.py finish                                  # close out the build
  tracker.py status                                  # print state summary
  tracker.py url                                     # print (and restart if needed) the page URL

Several tasks can run at once: `start 3 4 5`, then `done 4` as each finishes.
All commands take --dir DIR (default: ~/.build-tracker/<cwd folder name>).
Safe to call from parallel agents: every update holds a file lock.
"""
import argparse, contextlib, json, os, shutil, socket, subprocess, sys, time, webbrowser
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no flock; concurrent updates are not serialized
    fcntl = None

HERE = Path(__file__).resolve().parent


def now():
    return time.time()


def default_dir():
    return Path.home() / ".build-tracker" / Path.cwd().name


@contextlib.contextmanager
def locked(d):
    """Serialize read-modify-write so parallel agents don't overwrite each other."""
    with open(d / ".lock", "w") as f:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)


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
    if key.isdigit() and 1 <= int(key) <= len(s["tasks"]):
        return s["tasks"][int(key) - 1]
    for t in s["tasks"]:
        if t["name"].lower() == key.lower():
            return t
    sys.exit(f"No task '{key}'. Use a 1-based ID or exact name; see: tracker.py status")


def tid(s, t):
    return s["tasks"].index(t) + 1


def running(s):
    return [t for t in s["tasks"] if t["status"] == "running"]


def the_running(s, keys, example):
    """Tasks named by keys, or the single running task when no key is given."""
    if keys:
        return [find(s, k) for k in keys]
    r = running(s)
    if len(r) > 1:
        ids = ", ".join(f"{tid(s, t)} ({t['name']})" for t in r)
        sys.exit(f"{len(r)} tasks are running: {ids}. Say which one, e.g. tracker.py {example.format(tid(s, r[0]))}")
    return r


def finish_task(s, t, note):
    if t["status"] != "running":
        print(f"Not running, left as {t['status']}: {t['name']}")
        return
    t["status"], t["ended_at"] = "done", now()
    t.pop("live_note", None)
    if note:
        t["note"] = note
    print(f"Done: #{tid(s, t)} {t['name']} ({fmt(t['ended_at'] - t['started_at'])})")


def start_task(s, t=None):
    if t is None:
        t = next((x for x in s["tasks"] if x["status"] == "pending"), None)
        if t is None:
            print("No pending tasks.")
            return
    if t["status"] == "running":
        print(f"Already running: #{tid(s, t)} {t['name']}")
        return
    t["status"], t["started_at"], t["ended_at"] = "running", now(), None
    s["finished_at"] = None
    # Remember the most tasks seen running at once; the page's ETA schedules that many in parallel.
    s["workers"] = max(s.get("workers") or 1, len(running(s)))
    print(f"Started: #{tid(s, t)} {t['name']}")


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
    p.add_argument("--workers", type=int, default=1, help="tasks expected to run at once")
    p = sub.add_parser("add"); p.add_argument("name"); p.add_argument("--est", type=float)
    p = sub.add_parser("start"); p.add_argument("tasks", nargs="*")
    p = sub.add_parser("done"); p.add_argument("tasks", nargs="*"); p.add_argument("--note")
    p = sub.add_parser("next"); p.add_argument("task", nargs="?"); p.add_argument("--note")
    p = sub.add_parser("skip"); p.add_argument("task"); p.add_argument("--note")
    p = sub.add_parser("note"); p.add_argument("text"); p.add_argument("--task")
    p = sub.add_parser("workers"); p.add_argument("n", type=int)
    sub.add_parser("finish"); sub.add_parser("status"); sub.add_parser("url")
    a = ap.parse_args()
    d = (a.dir or default_dir()).expanduser().resolve()

    if a.cmd == "init":
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE / "index.html", d / "index.html")
        s = {"title": a.title, "created_at": now(), "finished_at": None, "workers": max(a.workers, 1),
             "tasks": [parse_task(x) for x in a.tasks]}
        with locked(d):
            save(d, s)
        url, _ = ensure_server(d)
        if not a.no_open:
            webbrowser.open(url)
        print(f"Tracker ready: {url}\nState: {d / 'state.json'}\nTasks: {len(s['tasks'])}")
        return
    if a.cmd == "url":
        load(d)
        url, restarted = ensure_server(d)
        print(url + ("  (server restarted)" if restarted else ""))
        return

    with locked(d):
        s = load(d)
        if a.cmd == "status":
            for i, t in enumerate(s["tasks"], 1):
                dur = fmt((t["ended_at"] or now()) - t["started_at"]) if t["started_at"] else ""
                print(f"{i:>2}. [{t['status']:<7}] {t['name']} {dur}")
            return
        if a.cmd == "add":
            s["tasks"].append(parse_task(a.name, a.est))
            s["finished_at"] = None
            print(f"Added #{len(s['tasks'])}: {s['tasks'][-1]['name']}")
        elif a.cmd == "start":
            for t in ([find(s, k) for k in a.tasks] or [None]):
                start_task(s, t)
        elif a.cmd == "done":
            ts = the_running(s, a.tasks, "done {}")
            if not ts:
                print("Nothing was running.")
            for t in ts:
                finish_task(s, t, a.note)
        elif a.cmd == "next":
            ts = the_running(s, [a.task] if a.task else [], "next {}")
            for t in ts:
                finish_task(s, t, a.note)
            start_task(s)
        elif a.cmd == "skip":
            t = find(s, a.task)
            t["status"], t["note"] = "skipped", a.note or t["note"]
            t.pop("live_note", None)
            print(f"Skipped: #{tid(s, t)} {t['name']}")
        elif a.cmd == "note":
            ts = the_running(s, [a.task] if a.task else [], 'note "..." --task {}')
            if not ts:
                sys.exit("No task is running; nothing to attach the note to.")
            ts[0]["live_note"] = a.text
            print(f"Note set on #{tid(s, ts[0])}.")
        elif a.cmd == "workers":
            s["workers"] = max(a.n, 1)
            print(f"Workers: {s['workers']}")
        elif a.cmd == "finish":
            for t in running(s):
                finish_task(s, t, None)
            s["finished_at"] = now()
            left = [t["name"] for t in s["tasks"] if t["status"] == "pending"]
            print("Build finished." + (f" Still pending: {', '.join(left)}" if left else ""))
        save(d, s)


if __name__ == "__main__":
    main()

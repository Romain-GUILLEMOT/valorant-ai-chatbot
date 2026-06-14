import json
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template, send_from_directory
import capture
import config
import vision
import shortcuts

SCAN_INTERVAL = 5
HOST = "127.0.0.1"
PORT = 8787

app = Flask(__name__)
state_lock = threading.Lock()

state = {
    "status": "starting",
    "current_game_id": 1,
    "last_signature": "",
    "score": {
        "allies": 0,
        "enemies": 0,
        "source": "manual",
        "updated_at": None
    },
    "games": [],
    "latest": {
        "scoreboard": [],
        "live_duels": [],
        "score": {
            "allies": 0,
            "enemies": 0,
            "source": "manual",
            "updated_at": None
        },
        "updated_at": None,
        "scan_ms": 0,
        "capture_ms": 0,
        "vision_ms": 0,
        "ocr_ms": 0,
        "template_ms": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "full_scan": False,
        "identity_changes": 0,
        "full_scan_reason": "startup"
    }
}

force_new_game = False

def save_state():
    os.makedirs(config.DEBUG_DIR, exist_ok=True)
    with open(os.path.join(config.DEBUG_DIR, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def reset_score(now=None):
    now = now or datetime.now().isoformat(timespec="seconds")
    state["score"] = {
        "allies": 0,
        "enemies": 0,
        "source": "manual",
        "updated_at": now
    }

def adjust_score(team, delta):
    if team not in ["allies", "enemies"]:
        return

    with state_lock:
        score = dict(state.get("score") or {})
        score["allies"] = max(0, int(score.get("allies", 0) or 0))
        score["enemies"] = max(0, int(score.get("enemies", 0) or 0))
        score[team] = max(0, score[team] + delta)
        score["source"] = "manual"
        score["updated_at"] = datetime.now().isoformat(timespec="seconds")
        state["score"] = score
        state.setdefault("latest", {})["score"] = dict(score)
        save_state()

    print(f"[shortcut] score allies={score['allies']} enemies={score['enemies']}")

def request_new_game_full_scan():
    global force_new_game

    with state_lock:
        force_new_game = True
        vision.force_full_scan()
        reset_score()
        state["latest"]["score"] = dict(state["score"])
        state["status"] = "full scan requested"
        save_state()

    print("[shortcut] new game requested + full scan forced + cache cleared")

def start_new_game(now):
    reset_score(now)
    state["current_game_id"] += 1
    state["games"].append({
        "id": state["current_game_id"],
        "started_at": now,
        "snapshots": []
    })

def ensure_game(now):
    if state["games"]:
        return

    state["games"].append({
        "id": state["current_game_id"],
        "started_at": now,
        "snapshots": []
    })

def update_game(scoreboard, live_duels, timings):
    global force_new_game

    now = datetime.now().isoformat(timespec="seconds")
    signature = vision.game_signature(scoreboard)
    new_game = False

    if force_new_game:
        new_game = True
        force_new_game = False
    elif (
        timings.get("full_scan")
        and timings.get("full_scan_reason") == "identity_change"
        and timings.get("identity_changes", 0) > 3
        and state["last_signature"]
    ):
        new_game = True

    if new_game:
        start_new_game(now)
    else:
        ensure_game(now)

    if signature:
        state["last_signature"] = signature

    snapshot = {
        "at": now,
        "scoreboard": scoreboard,
        "live_duels": live_duels,
        "score": dict(state["score"]),
        **timings
    }

    state["games"][-1]["snapshots"].append(snapshot)
    state["games"][-1]["snapshots"] = state["games"][-1]["snapshots"][-500:]

    state["latest"] = {
        "scoreboard": scoreboard,
        "live_duels": live_duels,
        "score": dict(state["score"]),
        "updated_at": now,
        **timings
    }

    state["status"] = "running"
    save_state()

def scan_once():
    t0 = time.perf_counter()

    hwnds = capture.find_tracker_hwnds()
    files = capture.capture_all_tracker_windows(hwnds)

    t1 = time.perf_counter()

    if files.get("scoreboard"):
        scoreboard = vision.parse_scoreboard(files.get("scoreboard"))
    else:
        vision.reset_metrics()
        scoreboard = []
    live_duels = vision.parse_live_duels(files.get("live_duels")) if files.get("live_duels") else []

    t2 = time.perf_counter()

    timings = {
        "capture_ms": round((t1 - t0) * 1000),
        "vision_ms": round((t2 - t1) * 1000),
        "scan_ms": round((t2 - t0) * 1000),
        "ocr_ms": vision.metrics["ocr_ms"],
        "template_ms": vision.metrics["template_ms"],
        "cache_hits": vision.metrics["cache_hits"],
        "cache_misses": vision.metrics["cache_misses"],
        "full_scan": vision.metrics["full_scan"],
        "identity_changes": vision.metrics["identity_changes"],
        "full_scan_reason": vision.metrics["full_scan_reason"]
    }

    with state_lock:
        update_game(scoreboard, live_duels, timings)

    scan_type = "FULL" if timings["full_scan"] else "FAST"
    print(
        f"[scan:{scan_type}] total={timings['scan_ms']}ms "
        f"capture={timings['capture_ms']}ms "
        f"vision={timings['vision_ms']}ms "
        f"ocr={timings['ocr_ms']}ms "
        f"tpl={timings['template_ms']}ms "
        f"cache={timings['cache_hits']}/{timings['cache_misses']} "
        f"identity_changes={timings['identity_changes']} "
        f"reason={timings['full_scan_reason']} "
        f"game={state['current_game_id']}"
    )

def scanner_loop():
    capture.boot_clean_directory()
    vision.load_templates_once()

    while True:
        try:
            scan_once()
        except Exception as e:
            with state_lock:
                state["status"] = f"error: {e}"
                save_state()
            print(f"[scan error] {e}")

        time.sleep(SCAN_INTERVAL)

def shortcut_loop():
    shortcuts.start_shortcuts(request_new_game_full_scan, adjust_score)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/state")
def api_state():
    with state_lock:
        return jsonify(state)

@app.post("/api/new-game")
def api_new_game():
    request_new_game_full_scan()
    return jsonify({"ok": True})

@app.post("/api/score/<team>/<direction>")
def api_score(team, direction):
    delta = 1 if direction == "up" else -1 if direction == "down" else 0

    if team not in ["allies", "enemies"] or delta == 0:
        return jsonify({"ok": False, "error": "expected /api/score/<allies|enemies>/<up|down>"}), 400

    adjust_score(team, delta)
    with state_lock:
        return jsonify({"ok": True, "score": state["score"]})

@app.get("/assets/agents/<path:filename>")
def agent_asset(filename):
    return send_from_directory(config.AGENTS_DIR, filename)

@app.get("/assets/ranks/<path:filename>")
def rank_asset(filename):
    return send_from_directory(config.RANKS_DIR, filename)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=shortcut_loop, daemon=True).start()

    print(f"[+] web: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

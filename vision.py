import hashlib
import os
import re
import time
import cv2
import numpy as np
import easyocr
import torch
import config

reader = None
agent_templates = []
rank_templates = []

static_ocr_cache = {}
static_visual_cache = {}

last_identity_hashes = []
last_static_rows = []
last_live_duel_static = []
force_full_scan_next = False
previous_dynamic_values = {}

metrics = {
    "ocr_ms": 0,
    "template_ms": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "full_scan": False,
    "identity_changes": 0,
    "full_scan_reason": "fast"
}

AGENT_NAMES = {
    "astra", "breach", "brimstone", "chamber", "clove", "cypher", "deadlock", "fade", "gekko", "harbor",
    "iso", "jett", "kayo", "killjoy", "neon", "omen", "phoenix", "raze", "reyna", "sage", "skye",
    "sova", "tejo", "viper", "vyse", "waylay", "yoru"
}

NAME_FIXES = {
    "veto": "vyse",
    "miks": "iso",
    "27": "radiant"
}

def force_full_scan():
    global last_identity_hashes, last_static_rows, last_live_duel_static, force_full_scan_next

    last_identity_hashes = []
    last_static_rows = []
    last_live_duel_static = []
    previous_dynamic_values.clear()
    static_ocr_cache.clear()
    static_visual_cache.clear()
    force_full_scan_next = True

def reset_metrics():
    metrics["ocr_ms"] = 0
    metrics["template_ms"] = 0
    metrics["cache_hits"] = 0
    metrics["cache_misses"] = 0
    metrics["full_scan"] = False
    metrics["identity_changes"] = 0
    metrics["full_scan_reason"] = "fast"

def ensure_reader():
    global reader

    if reader is not None:
        return

    print("[*] premier scan: warmup OCR...")

    if not torch.cuda.is_available():
        raise SystemError("GPU absent.")

    print(f"[+] GPU actif: {torch.cuda.get_device_name(0)}")

    reader = easyocr.Reader(["en"], gpu=True)
    reader.readtext(np.zeros((48, 160, 3), dtype=np.uint8), detail=0)

    print("[+] OCR prêt.")

def load_templates_once():
    global agent_templates, rank_templates

    agent_templates = load_templates(config.AGENTS_DIR, "agent")
    rank_templates = load_templates(config.RANKS_DIR, "rank")

    print(f"[+] templates loaded: agents={len(agent_templates)} ranks={len(rank_templates)}")

def r(value, total):
    return int(value * total)

def clean_text(value):
    value = re.sub(r"\s+", " ", (value or "").strip())

    fixes = {
        "З": "3",
        "з": "3",
        "О": "O",
        "о": "o",
        "І": "I",
        "і": "i",
        "Β": "B",
        "Е": "E"
    }

    for src, dst in fixes.items():
        value = value.replace(src, dst)

    return value

def can_mention(name):
    if not name or " " in name:
        return False

    return bool(re.fullmatch(r"[A-Za-z0-9_-]{3,24}", name))

def normalize_numeric_text(value, previous=""):
    raw = clean_text(value)
    normalized = raw.replace(" ", "").replace(",", ".").replace("\\", "/")

    # OCR confuses 0/O/o mostly inside numeric cells. Keep this out of names.
    normalized = re.sub(r"[Oo]", "0", normalized)
    normalized = re.sub(r"[Il]", "1", normalized)
    normalized = re.sub(r"[^0-9+\-/.%]", "", normalized)

    if not normalized and previous:
        return previous

    return normalized

def stat_clean(value, previous=""):
    return normalize_numeric_text(value, previous)

def normalize_asset_name(name):
    name = (name or "unknown").lower()
    return NAME_FIXES.get(name, name)

def img_hash(img):
    if img is None or img.size == 0:
        return ""

    small = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
    return hashlib.blake2b(small.tobytes(), digest_size=8).hexdigest()

def clamp_zone(img, zone):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = zone

    return (
        max(0, min(x1, w - 1)),
        max(0, min(y1, h - 1)),
        max(0, min(x2, w - 1)),
        max(0, min(y2, h - 1))
    )

def crop(img, zone):
    x1, y1, x2, y2 = clamp_zone(img, zone)
    return img[y1:y2, x1:x2]

def draw_zone(canvas, zone, color, label):
    x1, y1, x2, y2 = clamp_zone(canvas, zone)

    cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        canvas,
        label,
        (x1 + 2, y1 + 11),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.32,
        color,
        1,
        cv2.LINE_AA
    )

def crop_content(img, kind):
    if img is None or img.size == 0:
        return img

    if len(img.shape) == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        ys, xs = np.where(alpha > 10)

        if len(xs) and len(ys):
            pad = 3
            return img[
                max(0, ys.min() - pad):min(img.shape[0], ys.max() + pad),
                max(0, xs.min() - pad):min(img.shape[1], xs.max() + pad)
            ]

    if len(img.shape) == 3 and kind == "rank":
        bgr = img[:, :, :3]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 2] > 55) & (hsv[:, :, 1] > 22)).astype(np.uint8)
        ys, xs = np.where(mask > 0)

        if len(xs) and len(ys):
            pad = 4
            return img[
                max(0, ys.min() - pad):min(img.shape[0], ys.max() + pad),
                max(0, xs.min() - pad):min(img.shape[1], xs.max() + pad)
            ]

    return img

def rank_zone_has_rank(zone_img):
    if zone_img is None or zone_img.size == 0:
        return False

    bgr = zone_img[:, :, :3] if len(zone_img.shape) == 3 else cv2.cvtColor(zone_img, cv2.COLOR_GRAY2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    visible = ((hsv[:, :, 2] > 65) & (hsv[:, :, 1] > 30)).astype(np.uint8)
    count = int(np.sum(visible))

    return count >= 35

def make_feature(img, kind):
    img = crop_content(img, kind)

    if img is None or img.size == 0:
        return None

    bgr = img[:, :, :3] if len(img.shape) == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    size = (96, 96) if kind == "agent" else (72, 72)

    bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    if kind == "agent":
        mask = ((hsv[:, :, 2] > 35) & (hsv[:, :, 1] > 10)).astype(np.uint8) * 255
        h, w = mask.shape
        mask[int(h * 0.62):h, 0:int(w * 0.40)] = 0
    else:
        mask = ((hsv[:, :, 2] > 55) & (hsv[:, :, 1] > 22)).astype(np.uint8) * 255

    hist = cv2.calcHist(
        [hsv],
        [0, 1, 2],
        mask,
        [24, 10, 8],
        [0, 180, 0, 256, 0, 256]
    )
    cv2.normalize(hist, hist)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    edges = cv2.Canny(gray, 60, 150)

    return {
        "hist": hist,
        "gray": gray,
        "edges": edges
    }

def load_templates(folder, kind):
    out = []

    if not os.path.exists(folder):
        return out

    for filename in os.listdir(folder):
        if not filename.lower().endswith(".png"):
            continue

        name = normalize_asset_name(os.path.splitext(filename)[0])

        if kind == "rank" and name == "unknown":
            continue

        img = cv2.imread(os.path.join(folder, filename), cv2.IMREAD_UNCHANGED)
        feature = make_feature(img, kind)

        if feature:
            out.append({
                "name": name,
                "path": filename,
                "feature": feature
            })

    return out

def score_features(a, b, kind):
    hist = 1.0 - cv2.compareHist(a["hist"], b["hist"], cv2.HISTCMP_BHATTACHARYYA)
    gray = cv2.matchTemplate(a["gray"], b["gray"], cv2.TM_CCOEFF_NORMED)[0][0]
    edges = cv2.matchTemplate(a["edges"], b["edges"], cv2.TM_CCOEFF_NORMED)[0][0]

    if kind == "rank":
        return hist * 0.86 + gray * 0.10 + edges * 0.04

    return hist * 0.55 + gray * 0.30 + edges * 0.15

def visual_match(zone_img, templates, kind, use_cache=False, bypass_cache=False):
    if zone_img is None or zone_img.size == 0 or not templates:
        return "unknown", 0.0, ""

    if kind == "rank" and not rank_zone_has_rank(zone_img):
        return "unknown", 0.0, "unknown.png"

    key = f"{kind}:{img_hash(zone_img)}"

    if use_cache and not bypass_cache and key in static_visual_cache:
        metrics["cache_hits"] += 1
        return static_visual_cache[key]

    if use_cache:
        metrics["cache_misses"] += 1

    t0 = time.perf_counter()
    feature = make_feature(zone_img, kind)

    if feature is None:
        return "unknown", 0.0, ""

    scores = []

    for tpl in templates:
        score = score_features(feature, tpl["feature"], kind)
        scores.append((tpl["name"], float(score), tpl["path"]))

    scores.sort(key=lambda x: x[1], reverse=True)
    result = scores[0]

    if kind == "rank" and result[1] < 0.50:
        result = ("unknown", round(result[1], 3), "unknown.png")

    metrics["template_ms"] += round((time.perf_counter() - t0) * 1000)

    result = (result[0], round(result[1], 3), result[2])

    if use_cache:
        static_visual_cache[key] = result

    return result

def ocr(zone_img, allowlist=None, key_prefix="", use_cache=False, bypass_cache=False):
    ensure_reader()

    if zone_img is None or zone_img.size == 0:
        return ""

    key = f"{key_prefix}:{allowlist}:{img_hash(zone_img)}"

    if use_cache and not bypass_cache and key in static_ocr_cache:
        metrics["cache_hits"] += 1
        return static_ocr_cache[key]

    if use_cache:
        metrics["cache_misses"] += 1

    t0 = time.perf_counter()

    gray = cv2.cvtColor(zone_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    result = reader.readtext(gray, detail=0, paragraph=False, allowlist=allowlist)
    value = clean_text(" ".join(result))

    metrics["ocr_ms"] += round((time.perf_counter() - t0) * 1000)

    if use_cache:
        static_ocr_cache[key] = value

    return value

def read_live_digit(zone_img):
    if zone_img is None or zone_img.size == 0:
        return ""

    raw = ocr(zone_img, "0123456789", "live_digit", use_cache=False)
    value = re.sub(r"[^0-9]", "", raw)

    if value == "":
        return "0"

    if len(value) > 1:
        return value[-1]

    return value

def row_zone(row_y, row_h, x1, x2, y1_ratio=0.0, y2_ratio=1.0):
    return (x1, row_y + r(y1_ratio, row_h), x2, row_y + r(y2_ratio, row_h))

def level_zone(team_y, row_index, w, h):
    x1 = r(config.SB_LEVEL_X1, w)
    x2 = r(config.SB_LEVEL_X2, w)
    y1 = team_y + row_index * r(config.SB_LEVEL_ROW_STEP, h) + r(config.SB_LEVEL_Y_OFFSET, h)
    y2 = y1 + r(config.SB_LEVEL_ROW_H, h)

    return x1, y1, x2, y2

def scoreboard_zones(team_y, row_y, row_h, w, h, i):
    return {
        "agent": row_zone(
            row_y,
            row_h,
            r(config.SB_AGENT_X1, w),
            r(config.SB_AGENT_X2, w),
            config.SB_AGENT_Y1,
            config.SB_AGENT_Y2
        ),
        "level": level_zone(team_y, i, w, h),
        "name": row_zone(row_y, row_h, r(config.SB_NAME_X1, w), r(config.SB_NAME_X2, w)),
        "rank": row_zone(
            row_y,
            row_h,
            r(config.SB_RANK_X1, w),
            r(config.SB_RANK_X2, w),
            config.SB_RANK_Y1,
            config.SB_RANK_Y2
        ),
        "kd": row_zone(row_y, row_h, r(config.SB_KD_X1, w), r(config.SB_KD_X2, w)),
        "assists": row_zone(row_y, row_h, r(config.SB_ASSISTS_X1, w), r(config.SB_ASSISTS_X2, w)),
        "fkfd": row_zone(row_y, row_h, r(config.SB_FKFD_X1, w), r(config.SB_FKFD_X2, w)),
        "kd_ratio": row_zone(row_y, row_h, r(config.SB_KD_RATIO_X1, w), r(config.SB_KD_RATIO_X2, w)),
        "kpr": row_zone(row_y, row_h, r(config.SB_KPR_X1, w), r(config.SB_KPR_X2, w)),
        "esr": row_zone(row_y, row_h, r(config.SB_ESR_X1, w), r(config.SB_ESR_X2, w)),
        "kast": row_zone(row_y, row_h, r(config.SB_KAST_X1, w), r(config.SB_KAST_X2, w)),
        "srv": row_zone(row_y, row_h, r(config.SB_SRV_X1, w), r(config.SB_SRV_X2, w)),
        "hs": row_zone(row_y, row_h, r(config.SB_HS_X1, w), r(config.SB_HS_X2, w)),
        "one_v_x": row_zone(row_y, row_h, r(config.SB_1VX_X1, w), r(config.SB_1VX_X2, w))
    }

def identity_hashes(img):
    h, w = img.shape[:2]
    row_h = r(config.SB_ROW_H, h)
    row_step = r(config.SB_ROW_STEP, h)
    parts = []

    for team_y in [r(config.SB_TEAM1_Y, h), r(config.SB_TEAM2_Y, h)]:
        for i in range(5):
            row_y = team_y + i * row_step
            zones = scoreboard_zones(team_y, row_y, row_h, w, h, i)
            identity = crop(img, (
                zones["agent"][0],
                zones["agent"][1],
                zones["rank"][2],
                zones["name"][3]
            ))
            parts.append(img_hash(identity))

    return parts

def identity_hash(img):
    return "|".join(identity_hashes(img))

def changed_identity_count(current, previous):
    if not previous:
        return len(current)

    total = max(len(current), len(previous))
    changed = 0

    for i in range(total):
        if i >= len(current) or i >= len(previous) or current[i] != previous[i]:
            changed += 1

    return changed

def parse_static_scoreboard(img, bypass_cache=False):
    h, w = img.shape[:2]
    row_h = r(config.SB_ROW_H, h)
    row_step = r(config.SB_ROW_STEP, h)
    rows = []

    for team, team_y in [("allies", r(config.SB_TEAM1_Y, h)), ("enemies", r(config.SB_TEAM2_Y, h))]:
        for i in range(5):
            row_y = team_y + i * row_step
            zones = scoreboard_zones(team_y, row_y, row_h, w, h, i)

            name = clean_text(ocr(
                crop(img, zones["name"]),
                None,
                "name",
                use_cache=True,
                bypass_cache=bypass_cache
            ))

            lower = name.lower()

            if lower in AGENT_NAMES:
                agent = lower
                agent_score = 1.0
                agent_img = f"{lower}.png"
            else:
                agent, agent_score, agent_img = visual_match(
                    crop(img, zones["agent"]),
                    agent_templates,
                    "agent",
                    use_cache=True,
                    bypass_cache=bypass_cache
                )

            rank, rank_score, rank_img = visual_match(
                crop(img, zones["rank"]),
                rank_templates,
                "rank",
                use_cache=True,
                bypass_cache=bypass_cache
            )

            level_raw = ocr(
                crop(img, zones["level"]),
                "0123456789Oo",
                "level",
                use_cache=True,
                bypass_cache=bypass_cache
            )
            level = stat_clean(level_raw)

            rows.append({
                "team": team,
                "slot": i + 1,
                "agent": agent,
                "agent_score": agent_score,
                "agent_img": agent_img,
                "level_raw": level_raw,
                "level": level if level.isdigit() else "",
                "name": name,
                "can_mention": can_mention(name),
                "rank": rank,
                "rank_score": rank_score,
                "rank_img": rank_img
            })

    return rows

def parse_dynamic_scoreboard(img, static_rows):
    h, w = img.shape[:2]
    row_h = r(config.SB_ROW_H, h)
    row_step = r(config.SB_ROW_STEP, h)
    rows = []
    idx = 0

    for team, team_y in [("allies", r(config.SB_TEAM1_Y, h)), ("enemies", r(config.SB_TEAM2_Y, h))]:
        for i in range(5):
            row_y = team_y + i * row_step
            zones = scoreboard_zones(team_y, row_y, row_h, w, h, i)
            base = dict(static_rows[idx]) if idx < len(static_rows) else {"team": team, "slot": i + 1}

            def read_stat(field, zone_key, allowlist):
                cache_key = (team, i + 1, field)
                raw = ocr(crop(img, zones[zone_key]), allowlist, field, use_cache=False)
                normalized = stat_clean(raw, previous_dynamic_values.get(cache_key, ""))
                previous_dynamic_values[cache_key] = normalized
                return raw, normalized

            kd_raw, kd = read_stat("kd", "kd", "0123456789Oo-+/")
            assists_raw, assists = read_stat("assist", "assists", "0123456789Oo")
            fkfd_raw, fkfd = read_stat("fkfd", "fkfd", "0123456789Oo-/")
            kdr_raw, kd_ratio = read_stat("kdr", "kd_ratio", "0123456789Oo.,")
            kpr_raw, kpr = read_stat("kpr", "kpr", "0123456789Oo.,")
            esr_raw, esr = read_stat("esr", "esr", "0123456789Oo%")
            kast_raw, kast = read_stat("kast", "kast", "0123456789Oo%")
            srv_raw, srv = read_stat("srv", "srv", "0123456789Oo%")
            hs_raw, hs = read_stat("hs", "hs", "0123456789Oo%")
            one_v_x_raw, one_v_x = read_stat("1vx", "one_v_x", "0123456789Oo")

            base.update({
                "kd_raw": kd_raw,
                "kd": kd,
                "assists_raw": assists_raw,
                "assists": assists,
                "fkfd_raw": fkfd_raw,
                "fkfd": fkfd,
                "kd_ratio_raw": kdr_raw,
                "kd_ratio": kd_ratio,
                "kpr_raw": kpr_raw,
                "kpr": kpr,
                "esr_raw": esr_raw,
                "esr": esr,
                "kast_raw": kast_raw,
                "kast": kast,
                "srv_raw": srv_raw,
                "srv": srv,
                "hs_raw": hs_raw,
                "hs": hs,
                "one_v_x_raw": one_v_x_raw,
                "one_v_x": one_v_x
            })

            rows.append(base)
            idx += 1

    return rows

def parse_scoreboard(path):
    global last_identity_hashes, last_static_rows, force_full_scan_next

    reset_metrics()

    img = cv2.imread(path)

    if img is None:
        return []

    current_identity = identity_hashes(img)
    changed_players = changed_identity_count(current_identity, last_identity_hashes)
    must_full_scan = force_full_scan_next or not last_static_rows or changed_players > 3
    metrics["identity_changes"] = changed_players

    if must_full_scan:
        print(f"[vision] TRUE full static scan scoreboard changed_players={changed_players}")
        metrics["full_scan"] = True
        if force_full_scan_next:
            metrics["full_scan_reason"] = "manual_reset"
        elif not last_static_rows:
            metrics["full_scan_reason"] = "startup"
        else:
            metrics["full_scan_reason"] = "identity_change"
        last_identity_hashes = current_identity
        last_static_rows = parse_static_scoreboard(img, bypass_cache=force_full_scan_next)
        force_full_scan_next = False
    else:
        metrics["cache_hits"] += 10

    rows = parse_dynamic_scoreboard(img, last_static_rows)

    debug = img.copy()
    h, w = img.shape[:2]
    row_h = r(config.SB_ROW_H, h)
    row_step = r(config.SB_ROW_STEP, h)

    for team_y in [r(config.SB_TEAM1_Y, h), r(config.SB_TEAM2_Y, h)]:
        for i in range(5):
            row_y = team_y + i * row_step
            zones = scoreboard_zones(team_y, row_y, row_h, w, h, i)

            for key, color in {
                "agent": (255, 0, 0),
                "level": (255, 120, 0),
                "name": (0, 255, 0),
                "rank": (0, 255, 255),
                "kd": (0, 0, 255),
                "assists": (180, 180, 255),
                "fkfd": (180, 180, 255)
            }.items():
                draw_zone(debug, zones[key], color, key)

    cv2.imwrite(os.path.join(config.DEBUG_DIR, "VISUAL_DEBUG_SCOREBOARD.png"), debug)
    return rows

def live_duels_zones(h, w):
    zones = []

    for i in range(config.LD_COLS):
        x1 = r(config.LD_COL_START, w) + i * (r(config.LD_COL_W, w) + r(config.LD_COL_GAP, w))
        x2 = x1 + r(config.LD_COL_W, w)

        zones.append({
            "slot": i + 1,
            "agent": (x1, r(config.LD_AGENT_Y1, h), x2, r(config.LD_AGENT_Y2, h)),
            "kills": (x1, r(config.LD_KILLED_Y1, h), x2, r(config.LD_KILLED_Y2, h)),
            "deaths": (x1, r(config.LD_KILLED_BY_Y1, h), x2, r(config.LD_KILLED_BY_Y2, h))
        })

    return zones

def parse_live_duels(path):
    global last_live_duel_static

    img = cv2.imread(path)

    if img is None:
        return []

    rows = []
    debug = img.copy()

    for zones in live_duels_zones(*img.shape[:2]):
        draw_zone(debug, zones["agent"], (255, 0, 255), "agent")
        draw_zone(debug, zones["kills"], (0, 255, 255), "kills")
        draw_zone(debug, zones["deaths"], (0, 0, 255), "deaths")

        if metrics["full_scan"] or not last_live_duel_static or zones["slot"] > len(last_live_duel_static):
            agent, score, agent_img = visual_match(
                crop(img, zones["agent"]),
                agent_templates,
                "agent",
                use_cache=True,
                bypass_cache=metrics["full_scan"]
            )
            static = {
                "slot": zones["slot"],
                "agent": agent,
                "agent_score": score,
                "agent_img": agent_img
            }
        else:
            metrics["cache_hits"] += 1
            static = dict(last_live_duel_static[zones["slot"] - 1])

        rows.append({
            **static,
            "kills": read_live_digit(crop(img, zones["kills"])),
            "deaths": read_live_digit(crop(img, zones["deaths"]))
        })

    last_live_duel_static = [
        {
            "slot": row["slot"],
            "agent": row["agent"],
            "agent_score": row["agent_score"],
            "agent_img": row["agent_img"]
        }
        for row in rows
    ]

    cv2.imwrite(os.path.join(config.DEBUG_DIR, "VISUAL_DEBUG_LIVE_DUELS.png"), debug)
    return rows

def game_signature(rows):
    return "|".join(
        f"{row.get('team')}:{row.get('slot')}:{row.get('name','').lower()}:{row.get('agent')}:{row.get('rank')}"
        for row in rows
    )

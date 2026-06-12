"""
compile_database.py  ─  PSO2:NGS Knowledge-Base Builder  v10
=============================================================
Changes from v9:
- Every oversized file is now split into focused sub-files so
  no output file exceeds ~3 000 tokens.
- Overview sections are dropped entirely (always wiki nav menus).
- Section-level noise stripped: ▲▼ arrows, (C)SEGA, patch history,
  HTML render notices, wiki editor instructions.
- Class files split by weapon axis (general / sword-skills /
  wired-skills / partisan-skills / etc.)
- PA files split into actions_basics + individual move files
  (one file per PA for large weapons).
- Augments split into 5 focused sub-files.
- Enemy data split into type-overview / dolls-alters / formers-starless.
- Titles split into 3 category groups.
- Force / Techter / Bouncer / Braver split into general + weapon axes.
- Glossary removed from routing (too large, rarely useful).
"""

import urllib.request
import urllib.parse
import re
import os
import shutil
import time
import datetime

from bs4 import BeautifulSoup, NavigableString, Tag
from deep_translator import GoogleTranslator

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "HafuBotNGSDatabase/10.0"
    )
}

BASE_DIR        = "knowledge_base"
BASE_URL        = "https://pso2ngs.swiki.jp/index.php?"
MAX_SEC_CHARS   = 2_800   # hard cap per section after cleaning
TRANSLATE_CHUNK = 1_800   # max chars per single GoogleTranslator call

# ─────────────────────────────────────────────────────────────────────────────
# JUNK FILTERS
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKED_EXACT = {
    "コメント", "各PA動作フレーム数", "スクロール用スペース",
    "一覧", "テックアーツカスタマイズ", "▲", "▼", "▲▼",
    "概要",          # always a nav-menu blob — skip entirely
    "General Overview", "Overview",  # translated equivalents
}
_BLOCKED_SUBSTR = [
    "修正履歴", "変更履歴", "追加・変更",
    "Chain combo movement frame",   # frame-data tables in PA files
    "PA動作フレーム",
]

# Inline text patterns to strip even inside kept sections
_INLINE_NOISE = re.compile(
    r"("
    r"Notice from \[sWIKI\][^\n]*"              # wiki render-time notice
    r"|HTML ConvertTime[\d\. sec]*"
    r"|Weapons?/Armor \(Series\).*?(?=\n|$)"    # nav menu blob
    r"|Class \(Add-on Skill\).*?(?=\n|$)"
    r"|\(C\)SEGA[^\n]*"                         # copyright
    r"|Edit common items for this class[^\n]*"
    r"|Displaying the latest \d+ items\.[^\n]*"
    r"|See comment page[^\n]*"
    r"|Hide image[^\n]*"
    r"|Please refrain from making comments[^\n]*"
    r"|Lower PC body[^\n]*"
    r"|sWIKI \(lower tier for PC\)[^\n]*"
    r"|Below PC body[^\n]*"
    r"|Up to here[^\n]*"
    r"|If you would like to attach an icon image[^\n]*"
    r"|For more information, please see the WIKI[^\n]*"
    r"|Please refer to the Weapons/Armor/Series[^\n]*"
    r"|Table of Contents[^\n]*"
    r"|Open Table of Contents[^\n]*"
    r"|[▲▼]"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def _is_junk_section(title: str) -> bool:
    t = title.strip().replace(" ", "").replace("\u3000", "")
    if t in _BLOCKED_EXACT or title.strip() in _BLOCKED_EXACT:
        return True
    return any(sub in t for sub in _BLOCKED_SUBSTR)


def _strip_inline_noise(text: str) -> str:
    text = _INLINE_NOISE.sub(" ", text)
    text = re.sub(r"  +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

translator   = GoogleTranslator(source="ja", target="en")
_TRANS_CACHE = {}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _translate_chunk(chunk: str) -> str:
    if not chunk.strip():
        return ""
    if chunk in _TRANS_CACHE:
        return _TRANS_CACHE[chunk]
    for attempt in range(3):
        try:
            result = translator.translate(chunk)
            if result:
                _TRANS_CACHE[chunk] = result
                return result
        except Exception:
            if attempt < 2:
                time.sleep(1.5 ** attempt)
    return chunk


def safe_translate(text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[。、\.!?])|(?<=\n)", text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) > TRANSLATE_CHUNK:
            if current.strip():
                chunks.append(current.strip())
            while len(s) > TRANSLATE_CHUNK:
                chunks.append(s[:TRANSLATE_CHUNK])
                s = s[TRANSLATE_CHUNK:]
            current = s
        else:
            current += s
    if current.strip():
        chunks.append(current.strip())
    return " ".join(_translate_chunk(c) for c in chunks)


def fetch_url(url: str, timeout: int = 15, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:
            if attempt == retries - 1:
                raise exc
            time.sleep(2 ** attempt)


def get_ctable(soup: BeautifulSoup):
    contents = soup.find("div", id="contents")
    if not contents:
        return soup.find("div", id="body") or soup
    table = contents.find("table")
    if table:
        ctable = table.find("td", class_="ctable")
        if ctable:
            return ctable
    return contents


def extract_sections(ctable, skip_titles: set = None) -> list[tuple[str, str]]:
    """
    Extract (title, cleaned_text) pairs from the ctable.
    Always skips junk sections and Overview/概要 nav blobs.
    Optionally skips additional titles via skip_titles set.
    """
    if skip_titles is None:
        skip_titles = set()

    for el in ctable.find_all(id=re.compile(r"comment|reply|pcomment|vote", re.I)):
        el.decompose()
    for img in ctable.find_all("img"):
        img.decompose()

    sections: list[tuple[str, str]] = []
    current_title   = ""
    current_chunks: list[str] = []
    in_junk = False

    def flush():
        nonlocal current_chunks, in_junk
        if current_chunks and not in_junk:
            raw = clean_text(" ".join(current_chunks))
            raw = _strip_inline_noise(raw)
            if raw and len(raw) > 30:   # skip trivial empty sections
                if len(raw) > MAX_SEC_CHARS:
                    raw = raw[:MAX_SEC_CHARS] + " …[truncated]"
                sections.append((current_title, raw))
        current_chunks.clear()
        in_junk = False

    for node in ctable.descendants:
        if isinstance(node, NavigableString):
            if in_junk:
                continue
            pname = node.parent.name if node.parent else ""
            if pname not in ("script", "style", "h2", "h3"):
                t = str(node).strip()
                if t:
                    current_chunks.append(t)
        elif isinstance(node, Tag) and node.name in ("h2", "h3"):
            flush()
            title = node.get_text(strip=True)
            in_junk = _is_junk_section(title) or title.strip() in skip_titles
            current_title = title

    flush()
    return sections


def write_file(output_path: str, title: str, sections: list[tuple[str, str]],
               timestamp: str) -> None:
    """Translate and write sections to output_path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if not sections:
            f.write("(No content extracted)\n")
            return
        for sec_title, sec_text in sections:
            t_title = safe_translate(sec_title) if sec_title else ""
            t_body  = safe_translate(sec_text)
            if t_title:
                f.write(f"## {t_title}\n")
            f.write(t_body + "\n\n")


def write_placeholder(output_path: str, title: str, error: str,
                      timestamp: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n(Fetch failed: {error})\n")


def fetch_and_parse(jp_page: str) -> tuple:
    """Returns (soup, ctable) for a wiki page."""
    url   = BASE_URL + urllib.parse.quote(jp_page, safe="/")
    html  = fetch_url(url)
    soup  = BeautifulSoup(html, "html.parser")
    return soup, get_ctable(soup)


def sections_by_title(ctable, include: set) -> list[tuple[str, str]]:
    """Keep only sections whose title matches (case-insensitive) any item in include."""
    all_secs = extract_sections(ctable)
    inc_lower = {s.lower() for s in include}
    return [
        (t, c) for t, c in all_secs
        if any(k in t.lower() for k in inc_lower)
    ]


def sections_excluding(ctable, exclude_keywords: set) -> list[tuple[str, str]]:
    """Keep all sections except those matching exclude_keywords."""
    all_secs = extract_sections(ctable)
    exc_lower = {s.lower() for s in exclude_keywords}
    return [
        (t, c) for t, c in all_secs
        if not any(k in t.lower() for k in exc_lower)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# SPLIT HELPERS  ─  used for class files that share content across weapons
# ─────────────────────────────────────────────────────────────────────────────

def split_class_file(ctable,
                     general_keywords: set,
                     weapon_groups: list[tuple[str, set]]) -> dict[str, list]:
    """
    Partitions a class page into:
      'general'               → sections matching general_keywords
      weapon_groups[i][0]     → sections matching weapon_groups[i][1]
    Returns dict keyed by group name.
    """
    all_secs = extract_sections(ctable)
    result = {name: [] for name, _ in weapon_groups}
    result["general"] = []

    gen_lower = {k.lower() for k in general_keywords}

    for title, content in all_secs:
        tl = title.lower()
        matched = False
        for grp_name, grp_kws in weapon_groups:
            if any(k.lower() in tl for k in grp_kws):
                result[grp_name].append((title, content))
                matched = True
                break
        if not matched:
            if any(k in tl for k in gen_lower) or not tl:
                result["general"].append((title, content))
            else:
                # Default to general if unrecognised
                result["general"].append((title, content))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BUILD
# ─────────────────────────────────────────────────────────────────────────────

print("🚀 PSO2:NGS Database Compiler v10  ─  starting fresh build...", flush=True)

if os.path.exists(BASE_DIR):
    print(f"🧹 Clearing {BASE_DIR}/", flush=True)
    shutil.rmtree(BASE_DIR)
os.makedirs(BASE_DIR, exist_ok=True)

timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

# ══════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS
# ══════════════════════════════════════════════════════════════════════════════

for jp, (title, path) in {
    "FrontPage":   ("Front Page Registry",        "announcements/frontpage.txt"),
    "ミッションパス": ("Mission Pass Season Tracks", "announcements/mission_pass.txt"),
}.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# SEGA live feed
print(" → SEGA feed  ──►  announcements/sega_live_feed.txt", flush=True)
try:
    html = fetch_url("https://pso2.jp/players/update/", timeout=12)
    soup = BeautifulSoup(html, "html.parser")
    texts = [
        el.get_text(strip=True)
        for el in soup.find_all(["h2", "h3", "p"])
        if len(el.get_text(strip=True)) > 20
    ][:15]
    translated = safe_translate(" ".join(texts))
    p = os.path.join(BASE_DIR, "announcements/sega_live_feed.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# SEGA Live Announcements\n\n" + translated + "\n")
    print("   ✅  SEGA feed", flush=True)
except Exception as e:
    p = os.path.join(BASE_DIR, "announcements/sega_live_feed.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# SEGA Live Announcements\n\n(Feed unavailable)\n")
    print(f"   ⚠️  SEGA feed failed: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# CLASSES  ─  simple pages (no weapon-axis split needed)
# ══════════════════════════════════════════════════════════════════════════════

SIMPLE_CLASSES = {
    "クラス":    ("Class System Overview", "classes/class_overview.txt"),
    "EXスタイル": ("EX Style Mechanics",   "classes/ex_styles.txt"),
    "ガンナー":   ("Gunner Class Skills",  "classes/gunner.txt"),
    "レンジャー":  ("Ranger Class Skills",  "classes/ranger.txt"),
    "ウェイカー":  ("Waker Class Skills",   "classes/waker.txt"),
    "スレイヤー":  ("Slayer Class Skills",  "classes/slayer.txt"),
}

for jp, (title, path) in SIMPLE_CLASSES.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}  ({len(secs)} sections)", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# CLASSES  ─  split by weapon axis
# ══════════════════════════════════════════════════════════════════════════════

SPLIT_CLASSES = {
    # ── Hunter ────────────────────────────────────────────────────────────────
    "ハンター": {
        "title": "Hunter",
        "base":  "classes/hunter",
        "general_kws": {
            "overview", "class skill", "war cry", "massive hunter",
            "flash guard", "iron will", "just guard", "slow landing",
            "hunter arts", "hunter reflect",
        },
        "weapon_groups": [
            ("sword_skills",    {"sword arts", "sword attack", "sword guard", "sword sc"}),
            ("wired_skills",    {"wired", "crossing feathers"}),
            ("partisan_skills", {"partisan", "volgra", "assault charge", "assault avenge"}),
        ],
    },
    # ── Fighter ───────────────────────────────────────────────────────────────
    "ファイター": {
        "title": "Fighter",
        "base":  "classes/fighter",
        "general_kws": {
            "overview", "class skill", "fighter", "slow landing",
            "pp recovery", "chase advance", "subclass", "ex style",
        },
        "weapon_groups": [
            ("dagger_skills",  {"twin dagger", "twin daggers", "dagger arts", "dagger attack"}),
            ("saber_skills",   {"double saber", "saber arts", "saber attack"}),
            ("knuckle_skills", {"knuckle", "fist"}),
        ],
    },
    # ── Braver ────────────────────────────────────────────────────────────────
    "ブレイバー": {
        "title": "Braver",
        "base":  "classes/braver",
        "general_kws": {
            "overview", "class skill", "braver", "slow landing",
            "brave combat", "katana counter", "subclass", "ex style",
        },
        "weapon_groups": [
            ("katana_skills", {"katana", "blade arts", "cherry blossom", "sakura"}),
            ("rifle_skills",  {"assault rifle", "bullet", "charged shot", "final aim"}),
        ],
    },
    # ── Bouncer ───────────────────────────────────────────────────────────────
    "バウンサー": {
        "title": "Bouncer",
        "base":  "classes/bouncer",
        "general_kws": {
            "overview", "class skill", "defeat", "partial destroy",
            "physical decline", "elemental decline", "decline amplify",
            "decline geln", "special ability optimize bo",
            "foie brand", "barta blot", "sonde clad", "zangail",
            "grants glitter", "megidosphere", "slow landing",
            "subclass", "ex style",
        },
        "weapon_groups": [
            ("dual_blade_skills", {
                "fanatic blade", "photon blade", "blade counter",
                "blade arts", "pinion blade", "blade sc",
            }),
            ("jet_boots_skills", {
                "jet attack", "boot trick", "bounce counter",
                "thrust drive", "boot arts", "jet boots element",
                "sturmsieker",
            }),
        ],
    },
    # ── Force ─────────────────────────────────────────────────────────────────
    "フォース": {
        "title": "Force",
        "base":  "classes/force",
        "general_kws": {
            "overview", "class skill", "pp conversion", "pp recover",
            "pp gain", "killing pp", "technique charge", "lester",
            "slow landing", "foie brand", "barta blot", "sonde clad",
            "zangair", "grants glitter", "megidosphere",
            "long range", "unite technique", "photon flare",
            "technique domination", "subclass", "ex style",
        },
        "weapon_groups": [
            ("rod_skills",  {
                "elemental bullet", "rod technique", "elemental bullet extend",
                "keep rod", "rod charge", "rod attack", "rod react",
                "stay pp", "rod pp",
            }),
            ("talis_skills", {
                "tricky capacitor", "talis bloom", "float torchka",
                "talis sign", "talis revoke",
            }),
        ],
    },
    # ── Techter ───────────────────────────────────────────────────────────────
    "テクター": {
        "title": "Techter",
        "base":  "classes/techter",
        "general_kws": {
            "overview", "class skill", "shifter", "shifta", "deband",
            "reverse bounty", "weak element", "awake yale", "over emphasis",
            "foie brand", "barta blot", "sonde clad", "zangair",
            "grants glitter", "megidosphere", "long range advantage",
            "unite technique", "lester", "slow landing",
            "subclass", "ex style",
        },
        "weapon_groups": [
            ("wand_skills", {
                "won lovers", "won attack", "wondogard", "wand arts",
                "wondo technique", "wando technique", "wand element",
                "wondo element", "wondo parry", "wand parry",
            }),
            ("talis_skills", {
                "tricky capacitor", "talis bloom", "float torchka",
                "talis sign", "talis revoke",
            }),
        ],
    },
}

for jp, cfg in SPLIT_CLASSES.items():
    title_base = cfg["title"]
    base_path  = cfg["base"]
    print(f" → {jp}  ──►  {base_path}/*", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        groups = split_class_file(
            ctable,
            general_keywords=cfg["general_kws"],
            weapon_groups=cfg["weapon_groups"],
        )

        # Write general file
        gen_path = os.path.join(BASE_DIR, f"{base_path}_general.txt")
        write_file(gen_path, f"{title_base} — General Skills", groups["general"], timestamp)
        print(f"   ✅  {title_base} general ({len(groups['general'])} sections)", flush=True)

        # Write each weapon-axis file
        for grp_name, _ in cfg["weapon_groups"]:
            secs = groups[grp_name]
            out  = os.path.join(BASE_DIR, f"{base_path}_{grp_name}.txt")
            label = grp_name.replace("_", " ").title()
            write_file(out, f"{title_base} — {label}", secs, timestamp)
            print(f"   ✅  {title_base} {label} ({len(secs)} sections)", flush=True)

    except Exception as e:
        for suffix in ["_general", "_sword_skills", "_wired_skills", "_partisan_skills",
                       "_dagger_skills", "_saber_skills", "_knuckle_skills",
                       "_katana_skills", "_rifle_skills",
                       "_dual_blade_skills", "_jet_boots_skills",
                       "_rod_skills", "_talis_skills", "_wand_skills"]:
            p = os.path.join(BASE_DIR, f"{base_path}{suffix}.txt")
            write_placeholder(p, f"{title_base} ({suffix})", str(e), timestamp)
        print(f"   ❌  {jp}: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# WEAPONS  ─  overview pages (概要 only, no gear tables)
# ══════════════════════════════════════════════════════════════════════════════

WEAPON_OVERVIEWS = {
    "ソード":          ("Sword Overview",            "weapons/sword_overview.txt"),
    "ワイヤードランス":  ("Wired Lance Overview",       "weapons/wired_lance_overview.txt"),
    "パルチザン":       ("Partisan Overview",          "weapons/partisan_overview.txt"),
    "ツインダガー":     ("Twin Daggers Overview",      "weapons/twin_daggers_overview.txt"),
    "ダブルセイバー":   ("Double Saber Overview",      "weapons/double_saber_overview.txt"),
    "ナックル":         ("Knuckles Overview",          "weapons/knuckles_overview.txt"),
    "カタナ":          ("Katana Overview",             "weapons/katana_overview.txt"),
    "デュアルブレード":  ("Dual Blades Overview",       "weapons/dual_blades_overview.txt"),
    "アサルトライフル":  ("Assault Rifle Overview",     "weapons/assault_rifle_overview.txt"),
    "ランチャー":       ("Launcher Overview",          "weapons/launcher_overview.txt"),
    "ツインマシンガン":  ("Twin Machine Guns Overview", "weapons/twin_machineguns_overview.txt"),
    "バレットボウ":     ("Bullet Bow Overview",        "weapons/bullet_bow_overview.txt"),
    "ガンスラッシュ":   ("Gunslash Overview",          "weapons/gunslash_overview.txt"),
    "ロッド":          ("Rod Overview",                "weapons/rod_overview.txt"),
    "タリス":          ("Talis Overview",              "weapons/talis_overview.txt"),
    "ウォンド":         ("Wand Overview",              "weapons/wand_overview.txt"),
    "ジェットブーツ":   ("Jet Boots Overview",         "weapons/jet_boots_overview.txt"),
    "タクト":          ("Harmonizer Overview",         "weapons/harmonizer_overview.txt"),
}

for jp, (title, path) in WEAPON_OVERVIEWS.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        # Keep 概要 section only — drop 一覧 gear tables
        secs = sections_by_title(ctable, {"概要", "overview", "general"})
        if not secs:
            secs = extract_sections(ctable)[:2]   # fallback: first 2 sections
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# WEAPONS  ─  PA pages, each split into:
#   <weapon>_pa_basics.txt  — basic actions, normal attack, weapon action, generic
#   <weapon>_pa_<name>.txt  — one file per named PA/move
# ══════════════════════════════════════════════════════════════════════════════

# Sections that go into _basics vs individual PA files
_BASICS_KEYWORDS = {
    "basic action", "normal attack", "weapon action", "generic action",
    "photon blast", "about appropriate distance", "basic", "action",
}

PA_PAGES = {
    "ソード/アクション・PA":          ("Sword",          "weapons/sword"),
    "ワイヤードランス/アクション・PA":  ("Wired Lance",    "weapons/wired_lance"),
    "パルチザン/アクション・PA":        ("Partisan",       "weapons/partisan"),
    "ツインダガー/アクション・PA":      ("Twin Daggers",   "weapons/twin_daggers"),
    "ダブルセイバー/アクション・PA":    ("Double Saber",   "weapons/double_saber"),
    "ナックル/アクション・PA":          ("Knuckles",       "weapons/knuckles"),
    "カタナ/アクション・PA":            ("Katana",         "weapons/katana"),
    "デュアルブレード/アクション・PA":  ("Dual Blades",    "weapons/dual_blades"),
    "アサルトライフル/アクション・PA":  ("Assault Rifle",  "weapons/assault_rifle"),
    "ランチャー/アクション・PA":        ("Launcher",       "weapons/launcher"),
    "ツインマシンガン/アクション・PA":  ("Twin MGs",       "weapons/twin_machineguns"),
    "バレットボウ/アクション・PA":      ("Bullet Bow",     "weapons/bullet_bow"),
    "ガンスラッシュ/アクション・PA":    ("Gunslash",       "weapons/gunslash"),
    "ロッド/アクション・PA":            ("Rod",            "weapons/rod"),
    "タリス/アクション・PA":            ("Talis",          "weapons/talis"),
    "ウォンド/アクション・PA":          ("Wand",           "weapons/wand"),
    "ジェットブーツ/アクション・PA":    ("Jet Boots",      "weapons/jet_boots"),
    "タクト/アクション・PA":            ("Harmonizer",     "weapons/harmonizer"),
}

for jp, (weapon_name, base_path) in PA_PAGES.items():
    print(f" → {jp}  ──►  {base_path}_pa_*", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        all_secs = extract_sections(ctable)

        basics = []
        pa_files: dict[str, list] = {}   # safe_name → [(title, content)]

        for title, content in all_secs:
            tl = title.lower()
            if any(k in tl for k in _BASICS_KEYWORDS) or tl in ("", "photon arts"):
                basics.append((title, content))
            else:
                # Each named PA becomes its own file
                safe = re.sub(r"[^a-z0-9]+", "_", tl).strip("_")[:40]
                if safe not in pa_files:
                    pa_files[safe] = []
                pa_files[safe].append((title, content))

        # Write basics file
        basics_path = os.path.join(BASE_DIR, f"{base_path}_pa_basics.txt")
        write_file(basics_path, f"{weapon_name} — Basic Actions", basics, timestamp)

        # Write one file per PA
        for safe_name, secs in pa_files.items():
            pa_path = os.path.join(BASE_DIR, f"{base_path}_pa_{safe_name}.txt")
            pa_title = secs[0][0] if secs else safe_name
            write_file(pa_path, f"{weapon_name} PA — {pa_title}", secs, timestamp)

        total = 1 + len(pa_files)
        print(f"   ✅  {weapon_name}: basics + {len(pa_files)} PA files ({total} files)", flush=True)

    except Exception as e:
        write_placeholder(
            os.path.join(BASE_DIR, f"{base_path}_pa_basics.txt"),
            f"{weapon_name} PA Basics", str(e), timestamp,
        )
        print(f"   ❌  {jp}: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# WEAPONS  ─  series list + potentials (already small, keep as-is)
# ══════════════════════════════════════════════════════════════════════════════

for jp, (title, path) in {
    "武器・防具/シリーズ": ("Weapon & Armor Series List", "weapons/weapon_series.txt"),
    "潜在能力":           ("Weapon Potentials",          "mechanics/potentials.txt"),
}.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# MECHANICS  ─  small files (no split needed)
# ══════════════════════════════════════════════════════════════════════════════

SIMPLE_MECHANICS = {
    "防具":             ("Armor & Defensive Gear",       "mechanics/armor.txt"),
    "装備強化":          ("Equipment Enhancement",        "mechanics/equipment_enhancement.txt"),
    "アイテム強化・限界突破": ("Item Limit Breaking",       "mechanics/limit_breaking.txt"),
    "テクニック":        ("Elemental Techniques",         "mechanics/techniques.txt"),
    "アドオンスキル":     ("Add-on Skills System",        "mechanics/addon_skills.txt"),
    "プリセット能力":     ("Preset Abilities",            "mechanics/preset_abilities.txt"),
    "マルチウェポン":     ("Multi-Weapon System",         "mechanics/multi_weapon.txt"),
    "戦闘力":           ("Combat Power (BP) System",     "mechanics/combat_power.txt"),
    "状態異常・耐性":     ("Status Effects & Resistances","mechanics/status_effects.txt"),
    "クイックフード":     ("Quick Food Buffs",            "mechanics/quick_food.txt"),
}

for jp, (title, path) in SIMPLE_MECHANICS.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}  ({len(secs)} sections)", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# AUGMENTS  ─  split into 5 focused sub-files
# ══════════════════════════════════════════════════════════════════════════════

print(" → 特殊能力  ──►  mechanics/augments_*", flush=True)
try:
    _, ctable = fetch_and_parse("特殊能力")
    all_secs = extract_sections(ctable)

    # Group sections by keyword membership
    augment_groups = {
        "system": {
            "additional success rate", "number of special", "effects of special",
            "inheritance", "transferring", "auxiliary", "special ability list",
            "ac scratch", "list of special abilities that are effective",
        },
        "standard": {
            "stamina", "power", "shoot", "technique", "diable", "arm guard",
            "ability", "resist",
        },
        "boss": {
            "sole", "notes", "sobrina", "domina", "nilia", "decord", "secrete",
            "gigas", "dredo", "fusia", "scepter", "data", "weeker", "tria",
            "super", "dryel",
        },
        "enhance": {
            "enhancement experience", "weapon connector", "ac scratch product",
            "adi", "eddie", "nadi", "ladi", "yudi", "lase", "uze",
        },
        "special": {
            "defi", "duel quest", "season", "scheduled", "one capsule",
            "success rate improvement", "success rate period",
        },
    }

    groups: dict[str, list] = {k: [] for k in augment_groups}
    groups["system"] = []   # overview/intro always goes here

    for title, content in all_secs:
        tl = title.lower()
        placed = False
        for grp, kws in augment_groups.items():
            if any(k in tl for k in kws):
                groups[grp].append((title, content))
                placed = True
                break
        if not placed:
            groups["system"].append((title, content))

    aug_labels = {
        "system":   "Augments — System & How It Works",
        "standard": "Augments — Standard Types",
        "boss":     "Augments — Boss & Enemy-Specific",
        "enhance":  "Augments — Enhancement & AC Series",
        "special":  "Augments — Special & Duel Quest",
    }
    for grp, label in aug_labels.items():
        path = os.path.join(BASE_DIR, f"mechanics/augments_{grp}.txt")
        write_file(path, label, groups[grp], timestamp)
        print(f"   ✅  {label}  ({len(groups[grp])} sections)", flush=True)

except Exception as e:
    for grp in ["system", "standard", "boss", "enhance", "special"]:
        write_placeholder(
            os.path.join(BASE_DIR, f"mechanics/augments_{grp}.txt"),
            f"Augments ({grp})", str(e), timestamp,
        )
    print(f"   ❌  Augments: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# WORLD CONTENT
# ══════════════════════════════════════════════════════════════════════════════

SIMPLE_WORLD = {
    "タスク":      ("Main Tasks & Quests",   "world_quests/tasks.txt"),
    "緊急クエスト": ("Urgent Quests",        "world_quests/urgent_quests.txt"),
    "バトルディア": ("Battledia Quests",     "world_quests/battledia.txt"),
    "デュエルクエスト": ("Duel Quests",      "world_quests/duel_quests.txt"),
    "ルシエル探索": ("Leciel Exploration",   "world_quests/leciel_exploration.txt"),
    "ギャザリング": ("Gathering & Materials","world_quests/gathering.txt"),
}

for jp, (title, path) in SIMPLE_WORLD.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

# TITLES  ─  split into 3 category groups
print(" → 称号  ──►  world_quests/titles_*", flush=True)
try:
    _, ctable = fetch_and_parse("称号")
    all_secs = extract_sections(ctable)

    title_groups = {
        "player_items": {"player", "items", "overview"},
        "quests_tasks": {"quest", "tasks"},
        "other":        {"communication", "map", "limited"},
    }
    t_groups: dict[str, list] = {k: [] for k in title_groups}

    for title, content in all_secs:
        tl = title.lower()
        placed = False
        for grp, kws in title_groups.items():
            if any(k in tl for k in kws):
                t_groups[grp].append((title, content))
                placed = True
                break
        if not placed:
            t_groups["player_items"].append((title, content))

    title_labels = {
        "player_items": "Titles — Player & Items",
        "quests_tasks": "Titles — Quests & Tasks",
        "other":        "Titles — Communication, Map & Limited",
    }
    for grp, label in title_labels.items():
        path = os.path.join(BASE_DIR, f"world_quests/titles_{grp}.txt")
        write_file(path, label, t_groups[grp], timestamp)
        print(f"   ✅  {label}  ({len(t_groups[grp])} sections)", flush=True)

except Exception as e:
    for grp in ["player_items", "quests_tasks", "other"]:
        write_placeholder(
            os.path.join(BASE_DIR, f"world_quests/titles_{grp}.txt"),
            f"Titles ({grp})", str(e), timestamp,
        )
    print(f"   ❌  Titles: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# ENEMIES  ─  split into 3 files
# ══════════════════════════════════════════════════════════════════════════════

print(" → エネミー  ──►  enemies/enemy_*", flush=True)
try:
    _, ctable = fetch_and_parse("エネミー")
    all_secs = extract_sections(ctable)

    enemy_groups = {
        "types": {
            "rare", "enhanced", "dread", "gigantics", "season",
            "megalotix", "megalotic", "equaliz", "ancient", "giant mutant",
            "grocer", "bumble", "high energy", "different attribute",
            "enemy list",
        },
        "dolls_alters": {"doll", "alter"},
        "formers_starless": {"former", "starless", "ruinus", "tame", "other"},
    }
    e_groups: dict[str, list] = {"types": [], "dolls_alters": [], "formers_starless": []}

    for title, content in all_secs:
        tl = title.lower()
        placed = False
        for grp, kws in enemy_groups.items():
            if any(k in tl for k in kws):
                e_groups[grp].append((title, content))
                placed = True
                break
        if not placed:
            e_groups["types"].append((title, content))

    enemy_labels = {
        "types":           "Enemy Types & Overview",
        "dolls_alters":    "Enemies — Dolls & Alters",
        "formers_starless":"Enemies — Formers, Starless & Others",
    }
    for grp, label in enemy_labels.items():
        path = os.path.join(BASE_DIR, f"enemies/enemy_{grp}.txt")
        write_file(path, label, e_groups[grp], timestamp)
        print(f"   ✅  {label}  ({len(e_groups[grp])} sections)", flush=True)

except Exception as e:
    for grp in ["types", "dolls_alters", "formers_starless"]:
        write_placeholder(
            os.path.join(BASE_DIR, f"enemies/enemy_{grp}.txt"),
            f"Enemies ({grp})", str(e), timestamp,
        )
    print(f"   ❌  Enemies: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════════════════
# LORE  ─  worldview + NPC profiles (glossary intentionally excluded)
# ══════════════════════════════════════════════════════════════════════════════

for jp, (title, path) in {
    "世界観・ストーリー": ("World Lore & Story",          "lore/worldview_story.txt"),
    "登場NPC":          ("NPC Profiles & Character Lore","lore/npc_profiles.txt"),
}.items():
    print(f" → {jp}  ──►  {path}", flush=True)
    try:
        _, ctable = fetch_and_parse(jp)
        secs = extract_sections(ctable)
        write_file(os.path.join(BASE_DIR, path), title, secs, timestamp)
        print(f"   ✅  {title}", flush=True)
    except Exception as e:
        write_placeholder(os.path.join(BASE_DIR, path), title, str(e), timestamp)
        print(f"   ❌  {e}", flush=True)

print("\n✨ Compilation complete.", flush=True)

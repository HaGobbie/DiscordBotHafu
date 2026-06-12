"""
compile_database.py  ─  PSO2:NGS Knowledge-Base Builder
========================================================
Fetches wiki pages from pso2ngs.swiki.jp, strips junk, translates,
and writes clean .txt files that the bot uses for RAG lookups.

Key improvements over previous version
---------------------------------------
1. Correct content extraction  ─  reads the ctable (right column) instead
   of the whole page, so nav/sidebar text is gone entirely.
2. PA pages added  ─  every weapon now has a companion アクション・PA entry
   so the bot has real move names and descriptions instead of hallucinating.
3. Aggressive junk pruning  ─  drops コメント, 調整・修正履歴, 各PA動作フレーム数,
   スクロール用スペース, and 一覧 (gear-stat tables) before translation.
4. Smart 一覧 handling  ─  weapon overview pages keep the 概要 section but
   skip the massive per-rarity gear table that changes every patch.
5. Translation chunking  ─  never sends more than 1 800 chars at once to
   avoid GoogleTranslator 5 000-char limit; retries with back-off.
6. Per-page token budget  ─  each written section is capped at MAX_SECTION_CHARS
   so no single .txt file bloats the context window.
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
        "HafuBotNGSDatabase/8.0"
    )
}

BASE_DIR          = "knowledge_base"
BASE_URL          = "https://pso2ngs.swiki.jp/index.php?"
MAX_SECTION_CHARS = 3_000   # cap per section before translation (post-clean)
TRANSLATE_CHUNK   = 1_800   # max chars per single GoogleTranslator call

# ─────────────────────────────────────────────────────────────────────────────
# SECTION BLOCKLIST  ─  these h2/h3 titles are stripped wholesale
# ─────────────────────────────────────────────────────────────────────────────

# Exact matches (after stripping spaces/triangles)
_BLOCKED_EXACT = {
    "コメント",
    "各PA動作フレーム数",
    "スクロール用スペース",
    "一覧",                # giant gear-stat tables on weapon pages
    "テックアーツカスタマイズ",  # identical blurb repeated per-PA
    "▲", "▼", "▲▼",
}

# Substring matches (if any of these appear in the title, drop the section)
_BLOCKED_SUBSTR = [
    "修正履歴",   # 調整・修正履歴 / 追加・変更履歴  ─ patch notes
    "変更履歴",
    "追加・変更",
]


def _is_junk_section(title: str) -> bool:
    t = title.strip().replace(" ", "").replace("\u3000", "")
    if t in _BLOCKED_EXACT:
        return True
    return any(sub in t for sub in _BLOCKED_SUBSTR)


# ─────────────────────────────────────────────────────────────────────────────
# ASSET ROUTING MAP
# key   = Japanese wiki page name (used as URL query param)
# value = (English title for file header, output path relative to BASE_DIR)
#
# Weapon overview pages (ソード etc.)  → weapons/sword_overview.txt
# Weapon PA pages (ソード/アクション・PA) → weapons/sword_pa.txt
# ─────────────────────────────────────────────────────────────────────────────

ASSET_ROUTING_MAP = {

    # ── Announcements ─────────────────────────────────────────────────────────
    "FrontPage":          ("Front Page Registry",             "announcements/frontpage.txt"),
    "ミッションパス":        ("Mission Pass Season Tracks",      "announcements/mission_pass.txt"),

    # ── Classes ───────────────────────────────────────────────────────────────
    "クラス":              ("Class System Overview",           "classes/class_overview.txt"),
    "EXスタイル":          ("EX Style Mechanics",              "classes/ex_styles.txt"),
    "ハンター":             ("Hunter Class Skills",             "classes/hunter.txt"),
    "ファイター":           ("Fighter Class Skills",            "classes/fighter.txt"),
    "レンジャー":           ("Ranger Class Skills",             "classes/ranger.txt"),
    "ガンナー":             ("Gunner Class Skills",             "classes/gunner.txt"),
    "フォース":             ("Force Class Skills",              "classes/force.txt"),
    "テクター":             ("Techter Class Skills",            "classes/techter.txt"),
    "ブレイバー":           ("Braver Class Skills",             "classes/braver.txt"),
    "バウンサー":           ("Bouncer Class Skills",            "classes/bouncer.txt"),
    "ウェイカー":           ("Waker Class Skills",              "classes/waker.txt"),
    "スレイヤー":           ("Slayer Class Skills",             "classes/slayer.txt"),

    # ── Weapons: overview (概要 section only, no gear tables) ─────────────────
    "ソード":              ("Sword Weapon Overview",           "weapons/sword_overview.txt"),
    "ワイヤードランス":      ("Wired Lance Overview",            "weapons/wired_lance_overview.txt"),
    "パルチザン":           ("Partisan Overview",               "weapons/partisan_overview.txt"),
    "ツインダガー":         ("Twin Daggers Overview",           "weapons/twin_daggers_overview.txt"),
    "ダブルセイバー":        ("Double Saber Overview",           "weapons/double_saber_overview.txt"),
    "ナックル":             ("Knuckles Overview",               "weapons/knuckles_overview.txt"),
    "カタナ":              ("Katana Overview",                 "weapons/katana_overview.txt"),
    "デュアルブレード":      ("Dual Blades Overview",            "weapons/dual_blades_overview.txt"),
    "アサルトライフル":      ("Assault Rifle Overview",          "weapons/assault_rifle_overview.txt"),
    "ランチャー":           ("Launcher Overview",               "weapons/launcher_overview.txt"),
    "ツインマシンガン":      ("Twin Machine Guns Overview",      "weapons/twin_machineguns_overview.txt"),
    "バレットボウ":         ("Bullet Bow Overview",             "weapons/bullet_bow_overview.txt"),
    "ガンスラッシュ":        ("Gunslash Overview",               "weapons/gunslash_overview.txt"),
    "ロッド":              ("Rod Overview",                    "weapons/rod_overview.txt"),
    "タリス":              ("Talis Overview",                  "weapons/talis_overview.txt"),
    "ウォンド":             ("Wand Overview",                   "weapons/wand_overview.txt"),
    "ジェットブーツ":        ("Jet Boots Overview",              "weapons/jet_boots_overview.txt"),
    "タクト":              ("Harmonizer/Takt Overview",        "weapons/harmonizer_overview.txt"),

    # ── Weapons: Photon Arts / Actions (the pages with actual move data) ───────
    "ソード/アクション・PA":         ("Sword PAs & Actions",          "weapons/sword_pa.txt"),
    "ワイヤードランス/アクション・PA": ("Wired Lance PAs & Actions",    "weapons/wired_lance_pa.txt"),
    "パルチザン/アクション・PA":      ("Partisan PAs & Actions",       "weapons/partisan_pa.txt"),
    "ツインダガー/アクション・PA":    ("Twin Daggers PAs & Actions",   "weapons/twin_daggers_pa.txt"),
    "ダブルセイバー/アクション・PA":  ("Double Saber PAs & Actions",   "weapons/double_saber_pa.txt"),
    "ナックル/アクション・PA":        ("Knuckles PAs & Actions",       "weapons/knuckles_pa.txt"),
    "カタナ/アクション・PA":          ("Katana PAs & Actions",         "weapons/katana_pa.txt"),
    "デュアルブレード/アクション・PA":("Dual Blades PAs & Actions",    "weapons/dual_blades_pa.txt"),
    "アサルトライフル/アクション・PA":("Assault Rifle PAs & Actions",  "weapons/assault_rifle_pa.txt"),
    "ランチャー/アクション・PA":      ("Launcher PAs & Actions",       "weapons/launcher_pa.txt"),
    "ツインマシンガン/アクション・PA":("Twin MGs PAs & Actions",       "weapons/twin_machineguns_pa.txt"),
    "バレットボウ/アクション・PA":    ("Bullet Bow PAs & Actions",     "weapons/bullet_bow_pa.txt"),
    "ガンスラッシュ/アクション・PA":  ("Gunslash PAs & Actions",       "weapons/gunslash_pa.txt"),
    "ロッド/アクション・PA":          ("Rod Actions & Casts",          "weapons/rod_pa.txt"),
    "タリス/アクション・PA":          ("Talis PAs & Actions",          "weapons/talis_pa.txt"),
    "ウォンド/アクション・PA":        ("Wand PAs & Actions",           "weapons/wand_pa.txt"),
    "ジェットブーツ/アクション・PA":  ("Jet Boots PAs & Actions",      "weapons/jet_boots_pa.txt"),
    "タクト/アクション・PA":          ("Harmonizer PAs & Actions",     "weapons/harmonizer_pa.txt"),

    # ── Mechanics ─────────────────────────────────────────────────────────────
    "防具":                ("Armor & Defensive Gear",         "mechanics/armor.txt"),
    "装備強化":             ("Equipment Enhancement",          "mechanics/equipment_enhancement.txt"),
    "アイテム強化・限界突破": ("Item Limit Breaking",            "mechanics/limit_breaking.txt"),
    "テクニック":           ("Elemental Techniques",           "mechanics/techniques.txt"),
    "特殊能力":             ("Augments & Special Abilities",   "mechanics/augments.txt"),
    "アドオンスキル":        ("Add-on Skills System",           "mechanics/addon_skills.txt"),
    "潜在能力":             ("Weapon Potentials",              "mechanics/potentials.txt"),
    "プリセット能力":        ("Preset Abilities",               "mechanics/preset_abilities.txt"),
    "マルチウェポン":        ("Multi-Weapon System",            "mechanics/multi_weapon.txt"),
    "戦闘力":              ("Combat Power (BP) System",        "mechanics/combat_power.txt"),
    "状態異常・耐性":        ("Status Effects & Resistances",   "mechanics/status_effects.txt"),
    "クイックフード":        ("Quick Food Buffs",               "mechanics/quick_food.txt"),

    # ── World Content ──────────────────────────────────────────────────────────
    "タスク":              ("Main Tasks & Quests",             "world_quests/tasks.txt"),
    "緊急クエスト":         ("Urgent Quests",                  "world_quests/urgent_quests.txt"),
    "バトルディア":         ("Battledia Quests",               "world_quests/battledia.txt"),
    "デュエルクエスト":      ("Duel Quests",                    "world_quests/duel_quests.txt"),
    "ルシエル探索":         ("Leciel Exploration",             "world_quests/leciel_exploration.txt"),
    "ギャザリング":         ("Gathering & Materials",          "world_quests/gathering.txt"),
    "称号":               ("Titles & Achievements",           "world_quests/titles.txt"),

    # ── Enemies ───────────────────────────────────────────────────────────────
    "エネミー":             ("Enemy Species & Data",           "enemies/enemy_data.txt"),

    # ── Lore & Story ──────────────────────────────────────────────────────────
    "世界観・ストーリー":    ("World Lore & Story",             "lore/worldview_story.txt"),
    "登場NPC":             ("NPC Profiles & Character Lore",  "lore/npc_profiles.txt"),
    "用語集":              ("In-Universe Glossary",           "lore/glossary.txt"),
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

translator     = GoogleTranslator(source="ja", target="en")
_TRANS_CACHE   = {}          # simple in-process translation cache


def clean_text(text: str) -> str:
    """Collapse whitespace and remove stray HTML tags."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _translate_chunk(chunk: str) -> str:
    """Translate a single chunk ≤ TRANSLATE_CHUNK chars, with retry."""
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
    # Fall back to original text on persistent failure
    return chunk


def safe_translate(text: str) -> str:
    """
    Split text into ≤ TRANSLATE_CHUNK char pieces (on sentence boundaries
    where possible), translate each, and rejoin.
    """
    if not text:
        return ""

    # Split on Japanese sentence endings or plain newlines
    sentences = re.split(r"(?<=[。、\.!?])|(?<=\n)", text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) > TRANSLATE_CHUNK:
            if current.strip():
                chunks.append(current.strip())
            # If a single sentence is too long, hard-chop it
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
    """GET a URL, retry with exponential back-off on failure."""
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
    """
    Return the main-content table cell (class='ctable') which holds the
    actual wiki article body, separate from the left-side navigation column.
    Falls back to the whole #contents div if the layout changes.
    """
    contents = soup.find("div", id="contents")
    if not contents:
        return soup.find("div", id="body") or soup  # ultimate fallback

    table = contents.find("table")
    if table:
        ctable = table.find("td", class_="ctable")
        if ctable:
            return ctable

    return contents


def extract_sections(ctable, keep_only_overview: bool = False) -> list[tuple[str, str]]:
    """
    Walk the ctable and return a list of (section_title, cleaned_text) pairs
    after applying junk filters.

    keep_only_overview=True  ─  used for weapon overview pages; keeps only the
                                 概要 section and drops everything else (including
                                 the giant 一覧 gear table).
    """
    # Remove known junk elements in-place before iterating
    for el in ctable.find_all(id=re.compile(r"comment|reply|pcomment|vote", re.I)):
        el.decompose()
    # Remove image tags (no text value, just noise)
    for img in ctable.find_all("img"):
        img.decompose()

    sections: list[tuple[str, str]] = []
    current_title   = "Overview"
    current_chunks: list[str] = []
    in_junk_section = False

    def flush() -> None:
        nonlocal current_chunks, in_junk_section
        if current_chunks and not in_junk_section:
            raw = clean_text(" ".join(current_chunks))
            if raw:
                if len(raw) > MAX_SECTION_CHARS:
                    raw = raw[:MAX_SECTION_CHARS] + " …[truncated]"
                sections.append((current_title, raw))
        current_chunks.clear()
        in_junk_section = False

    for node in ctable.descendants:
        # ── plain text node ──────────────────────────────────────────────────
        if isinstance(node, NavigableString):
            if in_junk_section:
                continue
            parent_name = node.parent.name if node.parent else ""
            if parent_name not in ("script", "style", "h2", "h3"):
                text = str(node).strip()
                if text:
                    current_chunks.append(text)

        # ── element node: only care about headings ───────────────────────────
        elif isinstance(node, Tag) and node.name in ("h2", "h3"):
            flush()
            title = node.get_text(strip=True)
            if _is_junk_section(title):
                in_junk_section = True
            else:
                in_junk_section = False
            current_title = title  # always update so flush() uses right title

    flush()   # write final accumulated section

    if keep_only_overview:
        # For weapon overview pages keep only 概要 and any intro text before h2
        overview_titles = {"概要", "Overview", "General Overview", ""}
        return [(t, c) for t, c in sections if t in overview_titles]

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# MAIN COMPILATION LOOP
# ─────────────────────────────────────────────────────────────────────────────

print("🚀 PSO2:NGS Database Compiler v8  ─  starting fresh build...", flush=True)

# Wipe old output for a clean run
if os.path.exists(BASE_DIR):
    print(f"🧹 Clearing {BASE_DIR}/", flush=True)
    shutil.rmtree(BASE_DIR)
os.makedirs(BASE_DIR, exist_ok=True)

timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

for jp_page, (english_title, rel_path) in ASSET_ROUTING_MAP.items():
    url          = BASE_URL + urllib.parse.quote(jp_page, safe="/")
    output_path  = os.path.join(BASE_DIR, rel_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print(f" → {jp_page}  ──►  {rel_path}", flush=True)

    try:
        html  = fetch_url(url)
        soup  = BeautifulSoup(html, "html.parser")
        ctable = get_ctable(soup)

        # Weapon overview pages: strip gear tables, keep 概要 only
        is_weapon_overview = (
            "/アクション・PA" not in jp_page
            and rel_path.startswith("weapons/")
            and rel_path.endswith("_overview.txt")
        )
        sections = extract_sections(ctable, keep_only_overview=is_weapon_overview)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"=== [{english_title}] ===\n")
            f.write(f"=== COMPILED: {timestamp} ===\n\n")

            if not sections:
                f.write("(No content extracted)\n")
            else:
                for sec_title, sec_text in sections:
                    translated_title = safe_translate(sec_title) if sec_title else "Overview"
                    translated_body  = safe_translate(sec_text)
                    f.write(f"--- [{translated_title}] ---\n")
                    f.write(translated_body + "\n\n")

        print(f"   ✅  {english_title}  ({len(sections)} sections)", flush=True)

    except Exception as exc:
        print(f"   ❌  Failed: {jp_page}  ─  {exc}", flush=True)
        # Write an empty placeholder so the router never 404s on a missing file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"=== [{english_title}] ===\n")
            f.write(f"=== COMPILED: {timestamp} ===\n\n")
            f.write(f"(Fetch failed: {exc})\n")


# ─────────────────────────────────────────────────────────────────────────────
# SEGA OFFICIAL LIVE FEED  (top announcements from the JP players site)
# ─────────────────────────────────────────────────────────────────────────────

sega_path = os.path.join(BASE_DIR, "announcements/sega_live_feed.txt")
os.makedirs(os.path.dirname(sega_path), exist_ok=True)
print(" → SEGA official feed  ──►  announcements/sega_live_feed.txt", flush=True)

try:
    sega_url  = "https://pso2.jp/players/update/"
    sega_html = fetch_url(sega_url, timeout=12)
    sega_soup = BeautifulSoup(sega_html, "html.parser")

    # Pull h2/h3/p tags, min 20 chars, first 15 items to stay lightweight
    raw_texts = [
        el.get_text(strip=True)
        for el in sega_soup.find_all(["h2", "h3", "p"])
        if len(el.get_text(strip=True)) > 20
    ][:15]

    translated_feed = safe_translate(" ".join(raw_texts))

    with open(sega_path, "w", encoding="utf-8") as f:
        f.write("=== [LIVE FEED: SEGA OFFICIAL ANNOUNCEMENTS] ===\n")
        f.write(f"=== COMPILED: {timestamp} ===\n\n")
        f.write(translated_feed + "\n")

    print("   ✅  SEGA live feed saved.", flush=True)

except Exception as exc:
    with open(sega_path, "w", encoding="utf-8") as f:
        f.write("=== [LIVE FEED: SEGA OFFICIAL ANNOUNCEMENTS] ===\n")
        f.write(f"=== COMPILED: {timestamp} ===\n\n")
        f.write("(Feed unavailable at compile time)\n")
    print(f"   ⚠️  SEGA feed failed: {exc}", flush=True)


print("✨ Compilation complete.", flush=True)

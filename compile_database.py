"""
compile_database.py — PSO2:NGS Knowledge-Base Builder v12
==========================================================
Pipeline:
  1. MediaWiki API (action=parse) from pso2na.arks-visiphone.com
  2. BeautifulSoup → strip navigation / decoration noise
  3. HTML → tight plain-text (tables=pipe rows, headings, lists=dashes)
  4. Auto-split → no output file exceeds MAX_CHARS
  5. Descriptive filenames → AI router picks the right file by name alone

Source:  https://pso2na.arks-visiphone.com  (English wiki, NO translation needed)
Pages:   All under Portal:New_Genesis/... — discovered from the portal HTML
Resume:  Files already on disk are SKIPPED automatically (crash-safe)
         Run with --fresh to wipe and rebuild everything from scratch.
"""

import os
import re
import sys
import json
import glob
import time
import shutil
import datetime
import urllib.request
import urllib.parse

from bs4 import BeautifulSoup, NavigableString, Tag

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR    = "knowledge_base"
API_URL     = "https://pso2na.arks-visiphone.com/api.php"
MAX_CHARS   = 10_000   # per output file; auto-split above this
RATE_SLEEP  = 1.5      # seconds between API calls — wiki hits bandwidth limits
FRESH_BUILD    = "--fresh"         in sys.argv  # wipe and rebuild everything
RENAME_SPLITS  = "--rename-splits" in sys.argv  # rename existing split files (no network)

HEADERS = {
    "User-Agent": (
        "HafuBotNGS/12.0 (PSO2:NGS Discord Helper Bot; "
        "MediaWiki API client; educational/informational use)"
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# MEDIAWIKI API
# ─────────────────────────────────────────────────────────────────────────────

def api_get(params: dict, retries: int = 4) -> dict:
    """GET the MediaWiki API with exponential-backoff retry."""
    params["format"] = "json"
    qs  = urllib.parse.urlencode(params)
    url = f"{API_URL}?{qs}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            wait = 2 ** attempt
            if attempt < retries - 1:
                print(f"   ⏳ Attempt {attempt+1} failed ({exc!r}), "
                      f"retrying in {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise exc
    return {}


def fetch_html(title: str) -> str | None:
    """
    Fetch a wiki page as HTML via action=parse.
    Returns None if the page is missing / API returns an error.
    """
    data = api_get({
        "action": "parse",
        "page":   title,
        "prop":   "text",
        "disablelimitreport": "1",
        "disabletoc": "1",
    })
    if "error" in data:
        code = data["error"].get("code", "unknown")
        if code == "missingtitle":
            print(f"   ⚠️  [{title}] — page does not exist on wiki", flush=True)
        else:
            print(f"   ⚠️  [{title}] — API error: {code}", flush=True)
        return None
    return data.get("parse", {}).get("text", {}).get("*", None)


# ─────────────────────────────────────────────────────────────────────────────
# HTML → TIGHT PLAIN TEXT
# ─────────────────────────────────────────────────────────────────────────────

_DROP_SELECTORS = [
    ".navbox", ".navbox-inner", ".navbox-group", ".navbox-subgroup",
    ".navbox-even", ".navbox-odd",
    "#toc", ".toc",
    ".mw-editsection",
    "#catlinks", ".catlinks",
    ".mw-indicators", ".mw-indicator",
    ".sister-project", ".vertical-navbox",
    ".thumb", ".thumbinner", ".thumbcaption",
    "img", "figure",
    "style", "script",
    ".mw-empty-elt",
    ".hatnote",
    ".noprint", ".printfooter",
    ".mw-jump-link",
    "#footer", ".mw-footer",
    "sup.reference", "sup.cite_ref",
    ".reflist", ".references",
    ".mw-collapsible-toggle",
    ".mw-headline-anchor",
    ".sortkey",
]


def _clean(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for sel in _DROP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    return soup


def _table_to_text(table: Tag) -> str:
    """Convert an HTML table to compact pipe-delimited text rows."""
    lines = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        parts = []
        for cell in cells:
            txt = cell.get_text(separator=" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                parts.append(txt)
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def _node_to_text(el, out: list) -> None:
    """Recursively walk a BS4 node tree, appending tight text to out."""
    if isinstance(el, NavigableString):
        txt = str(el).strip()
        parent_name = el.parent.name if el.parent else ""
        if txt and parent_name not in {
            "h1","h2","h3","h4","h5","h6",
            "table","tr","td","th","ul","ol","li",
            "script","style",
        }:
            out.append(txt)
        return

    if not isinstance(el, Tag):
        return

    name = el.name

    if name in ("h1", "h2"):
        txt = el.get_text(strip=True)
        if txt:
            out.append(f"\n== {txt} ==")
        return

    if name in ("h3", "h4"):
        txt = el.get_text(strip=True)
        if txt:
            out.append(f"\n=== {txt} ===")
        return

    if name in ("h5", "h6"):
        txt = el.get_text(strip=True)
        if txt:
            out.append(f"-- {txt}")
        return

    if name == "table":
        txt = _table_to_text(el)
        if txt.strip():
            out.append(txt)
        return

    if name in ("ul", "ol"):
        for li in el.find_all("li", recursive=False):
            txt = li.get_text(separator=" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                out.append(f"- {txt}")
        return

    if name == "p":
        txt = el.get_text(separator=" ", strip=True)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt and len(txt) > 8:
            out.append(txt)
        return

    if name in ("td", "th", "tr"):
        return

    for child in el.children:
        _node_to_text(child, out)


def html_to_text(html: str) -> str:
    """Full pipeline: raw MediaWiki HTML → tight plain text."""
    soup  = _clean(html)
    body  = soup.find(class_="mw-parser-output") or soup
    out: list[str] = []
    for child in body.children:
        _node_to_text(child, out)

    text = "\n".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Drop known noise lines
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if re.match(
            r"^\[edit\]$|^Retrieved from|^Categories?:|^Navigation menu$",
            stripped, re.I
        ):
            continue
        kept.append(line)

    return "\n".join(kept).strip()


# ─────────────────────────────────────────────────────────────────────────────
# FILE WRITER WITH AUTO-SPLIT
# ─────────────────────────────────────────────────────────────────────────────

def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split text by == H2 == markers → [(safe_slug, section_text), ...]"""
    parts    = re.split(r"\n(== .+? ==)\n", text)
    sections = []
    intro    = parts[0].strip()
    if intro:
        sections.append(("intro", intro))
    i = 1
    while i < len(parts) - 1:
        heading = re.sub(r"^=+ | =+$", "", parts[i]).strip()
        body    = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")[:35]
            sections.append((slug, f"== {heading} ==\n{body}"))
        i += 2
    return sections


def _build_part_suffix(group: list[tuple[str, str]], max_len: int = 70) -> tuple[str, list[str]]:
    """
    Given a list of (slug, body) pairs for one split part, return:
      - a filename suffix string built from ALL section headings in the group
      - a list of human-readable heading names for the Sections header

    The suffix is capped at max_len chars; if it would overflow, the last
    element is replaced with "etc" so the router still knows more sections exist.
    """
    heading_names: list[str] = []
    heading_slugs: list[str] = []

    for slug, body in group:
        if slug == "intro":
            heading_names.append("Introduction")
            heading_slugs.append("intro")
        else:
            m = re.match(r"== (.+?) ==", body)
            name = m.group(1) if m else slug.replace("_", " ").title()
            heading_names.append(name)
            s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:22]
            heading_slugs.append(s)

    # Build suffix incrementally; append "_etc" when we'd exceed max_len
    suffix_parts: list[str] = []
    running_len = 0
    for s in heading_slugs:
        added = len(s) + (1 if suffix_parts else 0)   # +1 for underscore separator
        if running_len + added > max_len:
            suffix_parts.append("etc")
            break
        suffix_parts.append(s)
        running_len += added

    suffix = "_".join(suffix_parts) if suffix_parts else (heading_slugs[0] if heading_slugs else "part")
    return suffix, heading_names


def write_page(subpath: str, page_title: str, text: str) -> None:
    """
    Write text to BASE_DIR/<subpath>.txt.
    If text > MAX_CHARS, auto-split into …_part{N}_{all_section_slugs}.txt files.
    Each split file also gets a 'Sections in this file: …' header so the answer
    model immediately knows what topics the file covers.
    Each file is written individually — crash between splits only loses
    the unsaved parts, not previously completed pages.
    """
    if not text.strip():
        print(f"   ⚠️  Empty content for [{subpath}], skipping.", flush=True)
        return

    base_file = os.path.join(BASE_DIR, f"{subpath}.txt")
    os.makedirs(os.path.dirname(base_file), exist_ok=True)
    header = f"# {page_title}\n\n"

    if len(text) <= MAX_CHARS:
        with open(base_file, "w", encoding="utf-8") as f:
            f.write(header + text + "\n")
        print(f"   📄  {os.path.basename(base_file)}  ({len(text):,} chars)", flush=True)
        return

    # Split by h2 sections, bucket into groups ≤ MAX_CHARS
    sections = _split_sections(text)
    groups: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    cur_len = 0
    for slug, body in sections:
        if cur_len + len(body) > MAX_CHARS and cur:
            groups.append(cur)
            cur, cur_len = [], 0
        cur.append((slug, body))
        cur_len += len(body)
    if cur:
        groups.append(cur)

    if len(groups) == 1:
        truncated = text[:MAX_CHARS] + "\n\n[content continues at arks-visiphone.com]"
        with open(base_file, "w", encoding="utf-8") as f:
            f.write(header + truncated + "\n")
        print(f"   📄  {os.path.basename(base_file)}  (truncated, {MAX_CHARS:,} chars)", flush=True)
        return

    stem = base_file[:-4]   # drop .txt
    for i, group in enumerate(groups, 1):
        suffix, heading_names = _build_part_suffix(group)
        sub_path    = f"{stem}_part{i}_{suffix}.txt"
        sub_text    = "\n\n".join(body for _, body in group)
        sub_title   = f"{page_title} (Part {i})"
        sections_hdr = f"Sections in this file: {', '.join(heading_names)}\n\n"
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(f"# {sub_title}\n\n{sections_hdr}{sub_text}\n")
        print(f"   📄  {os.path.basename(sub_path)}  ({len(sub_text):,} chars)", flush=True)


def write_placeholder(subpath: str, page_title: str, error: str) -> None:
    """Write a placeholder so the bot starts cleanly even if a page failed."""
    path = os.path.join(BASE_DIR, f"{subpath}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {page_title}\n\n(Content unavailable: {error})\n")


def rename_splits_in_place() -> None:
    """
    --rename-splits mode: scan every existing _partN_* file in knowledge_base/,
    read its content, extract all H2 headings, rename with the full multi-section
    slug, and inject/update the 'Sections in this file:' header.

    No network calls — finishes in seconds.  Run this after upgrading from an
    older compile_database.py that only used the first section slug.
    """
    all_files = glob.glob(os.path.join(BASE_DIR, "**", "*.txt"), recursive=True)
    part_files = [f for f in all_files if re.search(r"_part\d+_", os.path.basename(f))]

    if not part_files:
        print("No split files found in knowledge_base/ — nothing to rename.", flush=True)
        return

    print(f"Found {len(part_files)} split file(s)...", flush=True)
    renamed = skipped = 0

    for old_path in sorted(part_files):
        with open(old_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract every H2 heading present in the file
        headings = re.findall(r"^== (.+?) ==$", content, re.MULTILINE)

        if not headings:
            print(f"   ⏭️  No H2 sections: {os.path.basename(old_path)}", flush=True)
            skipped += 1
            continue

        # Build new suffix from all headings (same logic as _build_part_suffix)
        heading_slugs = [
            re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")[:22]
            for h in headings
        ]
        suffix_parts: list[str] = []
        running = 0
        for s in heading_slugs:
            added = len(s) + (1 if suffix_parts else 0)
            if running + added > 70:
                suffix_parts.append("etc")
                break
            suffix_parts.append(s)
            running += added
        new_suffix = "_".join(suffix_parts) or heading_slugs[0]

        # Reconstruct path: everything up to and including _partN, then new suffix
        m = re.match(r"^(.+_part\d+)_(.+?)\.txt$", old_path)
        if not m:
            print(f"   ⚠️  Can't parse path: {os.path.basename(old_path)}", flush=True)
            skipped += 1
            continue

        new_path = f"{m.group(1)}_{new_suffix}.txt"

        # Inject or update the Sections header (line after the # title blank line)
        sections_line = f"Sections in this file: {', '.join(headings)}"
        if "Sections in this file:" in content:
            content = re.sub(
                r"^Sections in this file:.*$", sections_line,
                content, flags=re.MULTILINE
            )
        else:
            lines = content.split("\n")
            insert_at = 1
            while insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            lines.insert(insert_at, "")
            lines.insert(insert_at, sections_line)
            content = "\n".join(lines)

        # Write (always — even if path unchanged, we may have updated the header)
        with open(new_path, "w", encoding="utf-8") as f:
            f.write(content)

        if new_path != old_path:
            os.remove(old_path)
            print(
                f"   ✅  {os.path.basename(old_path)}\n"
                f"       → {os.path.basename(new_path)}",
                flush=True
            )
            renamed += 1
        else:
            print(f"   ✓   Header updated (name unchanged): {os.path.basename(new_path)}", flush=True)
            skipped += 1

    print(flush=True)
    print(f"✨ Done.  {renamed} renamed  |  {skipped} already optimal / no H2.", flush=True)
    if renamed:
        print("   Upload the updated knowledge_base/ folder to Render.", flush=True)


def already_done(subpath: str) -> bool:
    """
    Return True if this subpath already has any output file on disk.
    Checks for both the direct file and any auto-split part files.
    This is what makes the compiler crash-safe — re-running resumes
    from the last failed entry instead of restarting from scratch.
    """
    base = os.path.join(BASE_DIR, f"{subpath}.txt")
    if os.path.exists(base):
        return True
    stem  = os.path.join(BASE_DIR, subpath)
    parts = glob.glob(f"{stem}_part*.txt")
    return len(parts) > 0


# ─────────────────────────────────────────────────────────────────────────────
# FETCH + WRITE WITH FALLBACK TITLES
# ─────────────────────────────────────────────────────────────────────────────

def process_with_fallback(
    primary_title: str,
    subpath: str,
    desc_title: str,
    alternates: list[str] | None = None,
) -> bool:
    """
    Fetch primary_title; on 404 try each alternate.
    Writes the output file immediately on success.
    Returns True on success.
    """
    candidates = [primary_title] + (alternates or [])
    for title in candidates:
        time.sleep(RATE_SLEEP)
        print(f" → [{title}]  ──►  {subpath}", flush=True)
        try:
            html = fetch_html(title)
            if html is None:
                if len(candidates) > 1:
                    print(f"   ⚠️  Trying next candidate...", flush=True)
                continue
            text = html_to_text(html)
            if not text.strip():
                print(f"   ⚠️  Empty after cleaning, trying next...", flush=True)
                continue
            write_page(subpath, desc_title, text)
            return True
        except Exception as exc:
            print(f"   ❌  {type(exc).__name__}: {exc}", flush=True)
            if len(candidates) > 1:
                print(f"   ⚠️  Will try next candidate...", flush=True)

    write_placeholder(subpath, desc_title,
                      f"all title candidates failed: {candidates}")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# COMPLETE PAGE MANIFEST
#
# Source: Portal:New_Genesis HTML analysis — every link on the portal page.
# Format: (wiki_title, output_subpath, descriptive_title, [alternate_titles])
#
# output_subpath becomes the AI router's key.  Filenames are deliberately
# verbose so the router can pick the right one by reading the key name alone.
# ─────────────────────────────────────────────────────────────────────────────

MANIFEST: list[tuple[str, str, str, list[str]]] = [

    # ── EVENTS & LIVE CONTENT ─────────────────────────────────────────────────

    ("Portal:New_Genesis/Events",
     "events/current_events_limited_time_campaigns_and_event_details",
     "Current Events, Limited Time Campaigns and Event Details",
     []),

    ("Portal:New_Genesis/Mission_Pass",
     "events/mission_pass_seasonal_rewards_and_tracks",
     "Mission Pass Seasonal Rewards, Stars, and Prize Tracks",
     []),

    ("Portal:New_Genesis/Mission_Pass_Archive",
     "events/mission_pass_archive_past_seasons_and_prizes",
     "Mission Pass Archive — Past Seasons and Prize History",
     []),

    ("Portal:New_Genesis/Urgent_Quests",
     "events/urgent_quests_list_schedule_and_rewards",
     "Urgent Quests — List, Schedule and Rewards",
     []),

    ("Portal:New_Genesis/Campaigns",
     "events/campaigns_login_bonuses_and_promotional_events",
     "Campaigns, Login Bonuses and Promotional Events",
     []),

    ("Portal:New_Genesis/ARKS_Records",
     "events/arks_records_challenges_and_completion_rewards",
     "ARKS Records — Challenges and Completion Rewards",
     []),

    ("Portal:New_Genesis/Emergencies",
     "events/emergency_quests_and_emergency_notifications",
     "Emergency Quests and Emergency Notification System",
     []),

    ("Portal:New_Genesis/Limited_Time_Quests",
     "events/limited_time_quests_seasonal_exclusive",
     "Limited Time Quests — Seasonal and Event-Exclusive",
     []),

    ("Portal:New_Genesis/Seasonal_Points_Exchange_Shop",
     "events/seasonal_points_shop_and_point_exchange_rewards",
     "Seasonal Points Exchange Shop and Point Exchange Rewards",
     []),

    # ── CLASSES ───────────────────────────────────────────────────────────────

    ("Portal:New_Genesis/Class",
     "classes/class_system_overview_main_subclass_and_rules",
     "Class System Overview — Main Class, Subclass and Rules",
     []),

    ("Portal:New_Genesis/Character_Skills",
     "classes/character_skills_all_classes_skill_trees_and_points",
     "Character Skills — All Classes, Skill Trees and Skill Points",
     []),

    ("Portal:New_Genesis/EX_Style",
     "classes/ex_style_mechanics_unlock_conditions_and_bonus_stats",
     "EX Style — Mechanics, Unlock Conditions and Bonus Stats",
     []),

    ("Portal:New_Genesis/Hunter",
     "classes/hunter_class_guide_skills_sword_wired_lance_partisan",
     "Hunter Class Guide — Skills, Sword, Wired Lance and Partisan Arts",
     []),

    ("Portal:New_Genesis/Fighter",
     "classes/fighter_class_guide_skills_twin_daggers_double_saber_knuckles",
     "Fighter Class Guide — Skills, Twin Daggers, Double Saber and Knuckles",
     []),

    ("Portal:New_Genesis/Ranger",
     "classes/ranger_class_guide_skills_and_assault_rifle_photon_arts",
     "Ranger Class Guide — Skills and Assault Rifle Photon Arts",
     []),

    ("Portal:New_Genesis/Gunner",
     "classes/gunner_class_guide_skills_and_twin_machine_gun_photon_arts",
     "Gunner Class Guide — Skills and Twin Machine Gun Photon Arts",
     []),

    ("Portal:New_Genesis/Force",
     "classes/force_class_guide_skills_rod_talis_and_technique_casting",
     "Force Class Guide — Skills, Rod, Talis and Technique Casting",
     []),

    ("Portal:New_Genesis/Techter",
     "classes/techter_class_guide_skills_wand_talis_shifta_and_deband",
     "Techter Class Guide — Skills, Wand, Talis, Shifta and Deband",
     []),

    ("Portal:New_Genesis/Braver",
     "classes/braver_class_guide_skills_katana_and_assault_rifle",
     "Braver Class Guide — Skills, Katana and Assault Rifle Arts",
     []),

    ("Portal:New_Genesis/Bouncer",
     "classes/bouncer_class_guide_skills_dual_blades_and_jet_boots",
     "Bouncer Class Guide — Skills, Dual Blades and Jet Boots Arts",
     []),

    ("Portal:New_Genesis/Waker",
     "classes/waker_class_guide_skills_harmonizer_and_pet_mechanics",
     "Waker Class Guide — Skills, Harmonizer and Pet Mechanics",
     []),

    ("Portal:New_Genesis/Slayer",
     "classes/slayer_class_guide_skills_and_gunblade_photon_arts",
     "Slayer Class Guide — Skills and Gunblade Photon Arts",
     []),

    # ── WEAPONS & PHOTON ARTS ─────────────────────────────────────────────────

    ("Portal:New_Genesis/Weapon_Series",
     "weapons/weapon_series_comparison_meta_ranking_and_drop_sources",
     "Weapon Series — Comparison, Meta Ranking and Drop Sources",
     []),

    ("Portal:New_Genesis/Photon_Arts_List",
     "weapons/photon_arts_full_list_all_weapons_and_pa_details",
     "Photon Arts Full List — All Weapons and PA Details",
     []),

    ("Portal:New_Genesis/Tech_Arts_Customization",
     "weapons/tech_arts_customization_pa_charging_and_customization",
     "Tech Arts Customization — PA Charging and Customization System",
     []),

    ("Portal:New_Genesis/Photon_Blasts",
     "weapons/photon_blasts_types_activation_and_effects",
     "Photon Blasts — Types, Activation and Effects",
     []),

    # ── ITEM LAB / ENHANCEMENT / AUGMENTS ────────────────────────────────────

    ("Portal:New_Genesis/Item_Lab",
     "mechanics/item_lab_enhancement_limit_break_affixing_and_multiweapon",
     "Item Lab — Enhancement, Limit Break, Augment Affixing and Multi-Weapon",
     []),

    ("Portal:New_Genesis/List_of_Augments",
     "mechanics/augments_full_list_all_types_stats_and_drop_sources",
     "Augments Full List — All Types, Stats and Drop Sources",
     []),

    ("Portal:New_Genesis/Potentials",
     "mechanics/weapon_potentials_names_effects_and_unlock_conditions",
     "Weapon Potentials — Names, Effects and Unlock Conditions",
     []),

    ("Portal:New_Genesis/Armor",
     "mechanics/armor_and_defensive_units_stats_and_obtaining",
     "Armor and Defensive Units — Stats and How to Obtain",
     []),

    ("Portal:New_Genesis/Add-on_Skills",
     "mechanics/addon_skills_how_to_unlock_obtain_and_use",
     "Add-on Skills — How to Unlock, Obtain and Use",
     ["Portal:New_Genesis/Addon_Skills"]),

    ("Portal:New_Genesis/Special_Equipment",
     "mechanics/special_equipment_talisman_and_auxiliary_gear",
     "Special Equipment — Talisman and Auxiliary Gear",
     []),

    ("Portal:New_Genesis/Skill_Rings",
     "mechanics/skill_rings_types_and_stat_bonuses",
     "Skill Rings — Types and Stat Bonuses",
     []),

    # ── TECHNIQUES (MAGIC) ────────────────────────────────────────────────────

    ("Portal:New_Genesis/Techniques_List",
     "mechanics/techniques_elemental_spells_full_list_and_properties",
     "Techniques — Elemental Spells Full List, Fire/Ice/Lightning/Wind/Light/Dark",
     []),

    ("Portal:New_Genesis/Compound_Techniques_List",
     "mechanics/compound_techniques_combined_elements_and_list",
     "Compound Techniques — Combined Element Techs and Full List",
     []),

    # ── CORE MECHANICS ────────────────────────────────────────────────────────

    ("Portal:New_Genesis/Battle_Power",
     "mechanics/battle_power_bp_system_formula_and_gear_requirements",
     "Battle Power (BP) System — Formula and Gear Requirements",
     []),

    ("Portal:New_Genesis/Player_Status",
     "mechanics/player_status_stats_atk_def_and_attribute_breakdown",
     "Player Status — Stats, ATK, DEF and Attribute Breakdown",
     []),

    ("Portal:New_Genesis/Damage_Calculation",
     "mechanics/damage_formula_and_calculation_guide",
     "Damage Formula and Calculation Guide",
     []),

    ("Portal:New_Genesis/Status_Effects",
     "mechanics/status_effects_elemental_weaknesses_and_resistances",
     "Status Effects, Elemental Weaknesses and Resistances",
     []),

    ("Portal:New_Genesis/PSE",
     "mechanics/pse_photon_sensitive_explosion_burst_chain_mechanics",
     "PSE — Photon Sensitive Explosion, Burst and Chain Mechanics",
     []),

    ("Portal:New_Genesis/Experience_Level",
     "mechanics/experience_leveling_cap_and_bp_rewards_per_level",
     "Experience, Level Cap and BP Rewards Per Level",
     []),

    ("Portal:New_Genesis/Vital_Gauges",
     "mechanics/vital_gauges_hp_pp_photon_points_and_recovery",
     "Vital Gauges — HP, PP (Photon Points) and Recovery",
     []),

    ("Portal:New_Genesis/Weather",
     "mechanics/weather_system_effects_elemental_and_gathering_impact",
     "Weather System — Effects on Combat, Elemental Buffs and Gathering",
     []),

    ("Portal:New_Genesis/Region_Mags",
     "mechanics/region_mags_field_support_and_abilities",
     "Region Mags — Field Support and Abilities",
     []),

    ("Portal:New_Genesis/Mags",
     "mechanics/mags_personal_support_partner_and_photon_blasts",
     "Mags — Personal Support Partner and Photon Blasts",
     []),

    # ── FOOD & GATHERING ─────────────────────────────────────────────────────

    ("Portal:New_Genesis/Food",
     "mechanics/food_quick_food_cooking_stat_buffs_and_recipes",
     "Food, Quick Food, Cooking, Stat Buffs and Recipes",
     []),

    ("Portal:New_Genesis/Gathering",
     "mechanics/gathering_materials_resource_types_and_map_locations",
     "Gathering — Materials, Resource Types and Map Locations",
     []),

    # ── QUESTS & WORLD ────────────────────────────────────────────────────────

    ("Portal:New_Genesis/Quests",
     "world/quests_overview_all_quest_types_and_how_to_access",
     "Quests Overview — All Quest Types and How to Access",
     []),

    ("Portal:New_Genesis/Tasks",
     "world/tasks_daily_limited_time_and_main_task_list",
     "Tasks — Daily, Limited Time and Main Task List",
     []),

    ("Portal:New_Genesis/Main_Story",
     "world/main_story_quests_chapters_and_progression",
     "Main Story Quests — Chapters and Progression",
     []),

    ("Portal:New_Genesis/Battledia_Quests",
     "world/battledia_quests_yellow_red_and_trigger_types",
     "Battledia Quests — Yellow, Red and Trigger Types",
     []),

    ("Portal:New_Genesis/Duel_Quests",
     "world/duel_quests_solo_high_difficulty_boss_challenges",
     "Duel Quests — Solo High Difficulty Boss Challenges",
     []),

    ("Portal:New_Genesis/Standing_Quests",
     "world/standing_quests_repeatable_and_material_grinding",
     "Standing Quests — Repeatable and Material Grinding",
     []),

    ("Portal:New_Genesis/Trigger_Quests",
     "world/trigger_quests_item_activated_battles_and_rewards",
     "Trigger Quests — Item-Activated Battles and Rewards",
     []),

    ("Portal:New_Genesis/Trinitas_Quests",
     "world/trinitas_quests_high_tier_party_raids_and_rewards",
     "Trinitas Quests — High Tier Party Raids and Rewards",
     []),

    ("Portal:New_Genesis/Time_Extension_Quests",
     "world/time_extension_quests_and_mechanics",
     "Time Extension Quests and Mechanics",
     []),

    ("Portal:New_Genesis/Trainia_Advance_Quests",
     "world/trainia_advance_quests_tutorial_and_class_practice",
     "Trainia Advance Quests — Tutorial and Class Practice",
     []),

    ("Portal:New_Genesis/Field_Races",
     "world/field_races_time_trials_and_race_rewards",
     "Field Races — Time Trials and Race Rewards",
     []),

    ("Portal:New_Genesis/Major_Target_Suppression_Missions",
     "world/major_target_suppression_missions_boss_hunt_events",
     "Major Target Suppression Missions — Boss Hunt Events",
     []),

    ("Portal:New_Genesis/World_Trials",
     "world/world_trials_open_field_timed_events",
     "World Trials — Open Field Timed Events",
     []),

    ("Portal:New_Genesis/Cocoons_and_Towers",
     "world/cocoons_and_towers_training_challenges_and_bp_rewards",
     "Cocoons and Towers — Training Challenges and BP Rewards",
     []),

    # ── ENEMIES ───────────────────────────────────────────────────────────────

    ("Portal:New_Genesis/Enemies",
     "enemies/enemies_overview_factions_types_and_mechanics",
     "Enemies Overview — Factions, Types and Combat Mechanics",
     []),

    ("Portal:New_Genesis/Dolls",
     "enemies/dolls_enemy_faction_all_types_and_behavior",
     "DOLLS Enemy Faction — All Types and Behavior",
     []),

    ("Portal:New_Genesis/Alters",
     "enemies/alters_enemy_faction_all_types_and_behavior",
     "ALTERS Enemy Faction — All Types and Behavior",
     []),

    ("Portal:New_Genesis/Formers",
     "enemies/formers_enemy_faction_all_types_and_behavior",
     "Formers Enemy Faction — All Types and Behavior",
     []),

    ("Portal:New_Genesis/Starless",
     "enemies/starless_enemy_faction_all_types_and_behavior",
     "Starless Enemy Faction — All Types and Behavior",
     []),

    ("Portal:New_Genesis/Ruine",
     "enemies/ruine_enemy_faction_all_types_and_behavior",
     "Ruine Enemy Faction — All Types and Behavior",
     []),

    ("Portal:New_Genesis/Special_Enemies",
     "enemies/special_enemies_variants_and_unique_modifiers",
     "Special Enemies — Variants and Unique Modifiers",
     []),

    ("Portal:New_Genesis/Adras",
     "enemies/adras_enemy_type_guide_and_combat",
     "Adras Enemy Type — Guide and Combat",
     []),

    ("Portal:New_Genesis/Blitz",
     "enemies/blitz_enemy_type_guide_and_combat",
     "Blitz Enemy Type — Guide and Combat",
     []),

    ("Portal:New_Genesis/Celeste",
     "enemies/celeste_enemy_type_guide_and_combat",
     "Celeste Enemy Type — Guide and Combat",
     []),

    ("Portal:New_Genesis/Tames",
     "enemies/tames_capturable_creatures_and_abilities",
     "Tames — Capturable Creatures and Abilities",
     []),

    ("Portal:New_Genesis/MARS",
     "enemies/mars_combat_vehicle_type_and_mechanics",
     "MARS — Combat Vehicle Type and Mechanics",
     []),

    # ── WORLD / LORE ─────────────────────────────────────────────────────────

    ("Portal:New_Genesis/World",
     "lore/world_lore_regions_aelio_retem_kvaris_stia_and_leciel",
     "World Lore — Regions: Aelio, Retem, Kvaris, Stia and Leciel",
     []),

    ("Portal:New_Genesis/NPCs",
     "lore/npc_profiles_characters_and_arks_cast",
     "NPC Profiles — Characters and ARKS Cast",
     []),

    ("Portal:New_Genesis/NPC_Ronaldine",
     "lore/npc_ronaldine_profile_role_and_services",
     "NPC Ronaldine — Profile, Role and Services",
     []),

    # ── ECONOMY / CURRENCY / SHOPS ────────────────────────────────────────────

    ("Portal:New_Genesis/Currency",
     "economy/currency_meseta_star_gems_sg_and_ac",
     "Currency — Meseta, Star Gems (SG) and AC",
     []),

    ("Portal:New_Genesis/Shops",
     "economy/shops_and_vendors_all_types_and_locations",
     "Shops and Vendors — All Types and Locations",
     []),

    ("Portal:New_Genesis/Personal_Shop",
     "economy/personal_shop_player_to_player_trading",
     "Personal Shop — Player to Player Trading",
     []),

    ("Portal:New_Genesis/Exchange_Shops",
     "economy/exchange_shops_material_and_item_redemption",
     "Exchange Shops — Material and Item Redemption",
     []),

    ("Portal:New_Genesis/Items",
     "economy/items_overview_all_item_types_and_categories",
     "Items Overview — All Item Types and Categories",
     []),

    ("Portal:New_Genesis/Consumables",
     "economy/consumables_recovery_items_and_support_goods",
     "Consumables — Recovery Items and Support Goods",
     []),

    ("Portal:New_Genesis/Materials",
     "economy/materials_crafting_and_enhancement_resources",
     "Materials — Crafting and Enhancement Resources",
     []),

    ("Portal:New_Genesis/Collectables",
     "economy/collectables_and_collection_file_items",
     "Collectables and Collection File Items",
     []),

    ("Portal:New_Genesis/Reward_Boxes",
     "economy/reward_boxes_daily_weekly_and_event_boxes",
     "Reward Boxes — Daily, Weekly and Event Boxes",
     []),

    ("Portal:New_Genesis/Item_Packs",
     "economy/item_packs_and_dlc_bundles",
     "Item Packs and DLC Bundles",
     []),

    ("Portal:New_Genesis/Star_Gems_Shop",
     "economy/star_gems_shop_sg_purchasable_items",
     "Star Gems Shop — SG Purchasable Items",
     []),

    # ── AC SCRATCH / COSMETIC GACHA ───────────────────────────────────────────

    ("Portal:New_Genesis/AC_Scratches",
     "economy/ac_scratch_tickets_cosmetic_gacha_and_current_banner",
     "AC Scratch Tickets — Cosmetic Gacha and Current Banner",
     []),

    ("Portal:New_Genesis/SG_Scratches",
     "economy/sg_scratch_tickets_star_gem_gacha",
     "SG Scratch Tickets — Star Gem Gacha",
     []),

    ("Portal:New_Genesis/Treasure_Scratches",
     "economy/treasure_scratch_and_red_scratch_rewards",
     "Treasure Scratch and Red Scratch — Rewards",
     []),

    ("Portal:New_Genesis/Special_Scratches",
     "economy/special_scratches_limited_and_crossover_tickets",
     "Special Scratches — Limited and Crossover Tickets",
     []),

    ("Portal:New_Genesis/Revival_Scratches",
     "economy/revival_scratches_returning_cosmetics",
     "Revival Scratches — Returning Cosmetics",
     []),

    ("Portal:New_Genesis/ARKS_Cash_Shop",
     "economy/arks_cash_shop_ac_purchasable_items",
     "ARKS Cash Shop — AC Purchasable Items",
     []),

    # ── FASHION ───────────────────────────────────────────────────────────────

    ("Portal:New_Genesis/Fashion",
     "fashion/fashion_overview_costume_system_and_layering",
     "Fashion Overview — Costume System and Layering",
     []),

    ("Portal:New_Genesis/Beauty_Salon",
     "fashion/beauty_salon_character_customization_and_sliders",
     "Beauty Salon — Character Customization and Sliders",
     []),

    ("Portal:New_Genesis/Basewear",
     "fashion/basewear_body_costume_catalog",
     "Basewear — Body Costume Catalog",
     []),

    ("Portal:New_Genesis/Outerwear",
     "fashion/outerwear_jacket_and_coat_costume_catalog",
     "Outerwear — Jacket and Coat Costume Catalog",
     []),

    ("Portal:New_Genesis/Innerwear",
     "fashion/innerwear_undergarment_catalog",
     "Innerwear — Undergarment Catalog",
     []),

    ("Portal:New_Genesis/Setwear",
     "fashion/setwear_full_costume_set_catalog",
     "Setwear — Full Costume Set Catalog",
     []),

    ("Portal:New_Genesis/Full_Setwear",
     "fashion/full_setwear_complete_outfit_catalog",
     "Full Setwear — Complete Outfit Catalog",
     []),

    ("Portal:New_Genesis/Accessories",
     "fashion/accessories_and_attachment_item_catalog",
     "Accessories and Attachment Item Catalog",
     []),

    ("Portal:New_Genesis/Weapon_Camos",
     "fashion/weapon_camos_reskin_and_visual_catalog",
     "Weapon Camos — Reskin and Visual Catalog",
     []),

    ("Portal:New_Genesis/Hairstyles",
     "fashion/hairstyle_catalog_and_types",
     "Hairstyle Catalog and Types",
     []),

    ("Portal:New_Genesis/Color_Variants",
     "fashion/color_variants_and_dye_system",
     "Color Variants and Dye System",
     []),

    # ── SOCIAL / MULTIPLAYER ──────────────────────────────────────────────────

    ("Portal:New_Genesis/Friends",
     "social/friends_list_and_friend_system",
     "Friends List and Friend System",
     []),

    ("Portal:New_Genesis/Alliances",
     "social/alliances_guild_system_and_management",
     "Alliances — Guild System and Management",
     []),

    ("Portal:New_Genesis/Group_Chat",
     "social/group_chat_party_communication",
     "Group Chat and Party Communication",
     []),

    ("Portal:New_Genesis/ARKS_ID",
     "social/arks_id_player_profile_and_customization",
     "ARKS ID — Player Profile and Customization",
     []),

    ("Portal:New_Genesis/Symbol_Arts",
     "social/symbol_arts_custom_icons_and_sharing",
     "Symbol Arts — Custom Icons and Sharing",
     []),

    ("Portal:New_Genesis/Emotes",
     "social/emotes_and_chat_actions",
     "Emotes and Chat Actions",
     []),

    ("Portal:New_Genesis/Motions",
     "social/motions_and_idle_animations",
     "Motions and Idle Animations",
     []),

    ("Portal:New_Genesis/Creative_Space",
     "social/creative_space_housing_building_and_furniture",
     "Creative Space — Housing, Building and Furniture",
     []),

    # ── ACHIEVEMENTS / TITLES ─────────────────────────────────────────────────

    ("Portal:New_Genesis/Achievements",
     "achievements/achievements_and_medal_rewards",
     "Achievements and Medal Rewards",
     []),

    ("Portal:New_Genesis/Titles",
     "achievements/titles_how_to_earn_and_rewards",
     "Titles — How to Earn and Rewards",
     []),

    ("Portal:New_Genesis/Cumulative_Title_List",
     "achievements/cumulative_title_list_all_titles_and_conditions",
     "Cumulative Title List — All Titles and Unlock Conditions",
     []),

    # ── MINI-GAME: LINE STRIKE ────────────────────────────────────────────────

    ("Portal:New_Genesis/Line_Strike",
     "minigame/line_strike_card_game_overview_and_rules",
     "Line Strike — Card Game Overview and Rules",
     []),

    ("Portal:New_Genesis/Card_List",
     "minigame/line_strike_card_list_and_effects",
     "Line Strike Card List and Effects",
     []),

    ("Portal:New_Genesis/Sleeves",
     "minigame/line_strike_sleeves_cosmetics",
     "Line Strike Sleeves Cosmetics",
     []),

    ("Portal:New_Genesis/Mats",
     "minigame/line_strike_play_mats_cosmetics",
     "Line Strike Play Mats Cosmetics",
     []),

    # ── SYSTEM / INTERFACE ────────────────────────────────────────────────────

    ("Portal:New_Genesis/Item_Codes_and_Keywords",
     "system/item_codes_and_keywords_how_to_redeem",
     "Item Codes and Keywords — How to Redeem",
     []),

    ("Portal:New_Genesis/Chat_Commands",
     "system/chat_commands_and_shortcuts",
     "Chat Commands and Shortcuts",
     []),

    ("Portal:New_Genesis/Loading_Tips",
     "system/loading_tips_and_gameplay_hints",
     "Loading Tips and Gameplay Hints",
     []),

    ("Portal:New_Genesis/Login_Stamps",
     "system/login_stamps_and_daily_login_bonuses",
     "Login Stamps and Daily Login Bonuses",
     []),

    ("Portal:New_Genesis/Updates",
     "system/game_version_updates_and_patch_notes",
     "Game Version Updates and Patch Notes",
     []),

    ("Portal:New_Genesis/Storage",
     "system/storage_and_inventory_management",
     "Storage and Inventory Management",
     []),

    ("Portal:New_Genesis/Inventory",
     "system/inventory_item_capacity_and_management",
     "Inventory — Item Capacity and Management",
     []),
]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"🚀 PSO2:NGS DB Compiler v12  |  {timestamp}", flush=True)
    print(f"   Source : pso2na.arks-visiphone.com  (EN wiki, no translation)", flush=True)
    print(f"   Output : {BASE_DIR}/   Max chars/file: {MAX_CHARS:,}", flush=True)
    print(f"   Pages  : {len(MANIFEST)} entries in MANIFEST", flush=True)
    print(flush=True)

    # ── --rename-splits: fix existing split file names without re-scraping ────
    if RENAME_SPLITS:
        print("🔧 Mode: --rename-splits  (no network calls, reads local files only)", flush=True)
        print(flush=True)
        rename_splits_in_place()
        sys.exit(0)

    if FRESH_BUILD:
        if os.path.exists(BASE_DIR):
            print(f"🧹 --fresh: wiping {BASE_DIR}/", flush=True)
            shutil.rmtree(BASE_DIR)
        print(flush=True)
    else:
        print(f"   Mode   : RESUME — files already on disk will be skipped.", flush=True)
        print(f"            (Use --fresh to force a full rebuild)", flush=True)
        print(flush=True)

    os.makedirs(BASE_DIR, exist_ok=True)

    ok_count      = 0
    skip_count    = 0
    err_count     = 0
    total         = len(MANIFEST)

    for idx, (wiki_title, subpath, desc_title, alts) in enumerate(MANIFEST, 1):
        print(f"[{idx:>3}/{total}]", end=" ", flush=True)

        # ── RESUME CHECK ──────────────────────────────────────────────────────
        if already_done(subpath):
            print(f"⏭️  SKIP (already done): {subpath}", flush=True)
            skip_count += 1
            ok_count   += 1    # counts as done for final tally
            continue

        # ── FETCH + WRITE ─────────────────────────────────────────────────────
        success = process_with_fallback(wiki_title, subpath, desc_title, alts)
        if success:
            ok_count += 1
        else:
            err_count += 1

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print(flush=True)
    print("=" * 60, flush=True)
    print(f"✨ Done.  {ok_count}/{total} succeeded  |  "
          f"{skip_count} skipped (resume)  |  {err_count} failed", flush=True)

    if err_count:
        print(flush=True)
        print("ℹ️  Failed pages were written as placeholders so the bot starts.", flush=True)
        print("   Re-run (without --fresh) to retry only the failed ones.", flush=True)
        print("   Check ⚠️  / ❌ lines above to diagnose page-title issues.", flush=True)
    else:
        print("🌸 All pages complete. Upload knowledge_base/ to Render.", flush=True)

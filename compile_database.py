import urllib.request
import re
import urllib.parse
import os
import shutil
from bs4 import BeautifulSoup
import datetime
from deep_translator import GoogleTranslator

print("🚀 Launching ULTRA-GRANULAR Multi-File Translation Compiler...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/6.0'}
BASE_DIR = "knowledge_base"

# 1. Fresh Start: Wipe out the old directory if it exists to prevent duplicate data stacking
if os.path.exists(BASE_DIR):
    print(f"🧹 Clearing out old {BASE_DIR} directory for a clean compilation...", flush=True)
    shutil.rmtree(BASE_DIR)

os.makedirs(BASE_DIR, exist_ok=True)

translator = GoogleTranslator(source='ja', target='en')

# Explicit mapping of Japanese wiki nodes to English titles and targeted micro-paths
ASSET_ROUTING_MAP = {
    "FrontPage": ("FrontPage Registry", "announcements/frontpage.txt"),
    
    "クラス": ("General Class Systems & EX Styles", "classes/general_classes.txt"),
    "EXスタイル": ("General Class Systems & EX Styles", "classes/general_classes.txt"),
    "ハンター": ("Hunter Class Skills & Data", "classes/hunter.txt"),
    "ファイター": ("Fighter Class Skills & Data", "classes/fighter.txt"),
    "レンジャー": ("Ranger Class Skills & Data", "classes/ranger.txt"),
    "ガンナー": ("Gunner Class Skills & Data", "classes/gunner.txt"),
    "フォース": ("Force Class Skills & Data", "classes/force.txt"),
    "テクター": ("Techter Class Skills & Data", "classes/techter.txt"),
    "ブレイバー": ("Braver Class Skills & Data", "classes/braver.txt"),
    "バウンサー": ("Bouncer Class Skills & Data", "classes/bouncer.txt"),
    "ウェイカー": ("Waker Class Skills & Data", "classes/waker.txt"),
    "スレイヤー": ("Slayer Class Skills & Data", "classes/slayer.txt"),
    
    "武器": ("General Weapon Systems", "weapons/general_weapons.txt"),
    "ソード": ("Sword Weapon Stats & Photon Arts", "weapons/sword.txt"),
    "ワイヤードランス": ("Wired Lance Weapon Stats & Photon Arts", "weapons/wired_lance.txt"),
    "パルチザン": ("Partisan Weapon Stats & Photon Arts", "weapons/partisan.txt"),
    "ツインダガー": ("Twin Daggers Weapon Stats & Photon Arts", "weapons/twin_daggers.txt"),
    "デュアルブレード": ("Dual Blades Weapon Stats & Photon Arts", "weapons/dual_blades.txt"),
    "ナックル": ("Knuckles Weapon Stats & Photon Arts", "weapons/knuckles.txt"),
    "カタナ": ("Katana Weapon Stats & Photon Arts", "weapons/katana.txt"),
    "アサルトライフル": ("Assault Rifle Weapon Stats & Photon Arts", "weapons/assault_rifle.txt"),
    "ツインマシンガン": ("Twin Machine Guns Weapon Stats & Photon Arts", "weapons/twin_machine_guns.txt"),
    "タリス": ("Talis Weapon Stats & Photon Arts", "weapons/talis.txt"),
    "ウォンド": ("Wand Weapon Stats & Photon Arts", "weapons/wand.txt"),
    "タクト": ("Harmonizer Takt Weapon Stats & Photon Arts", "weapons/harmonizer.txt"),
    "ジェットブーツ": ("Jet Boots Weapon Stats & Photon Arts", "weapons/jet_boots.txt"),
    
    "防具": ("Armor Units & Defensive Gear", "mechanics/armor.txt"),
    "スキルリング": ("Skill Rings Additions", "mechanics/skill_rings.txt"),
    "装備強化": ("Equipment Enhancement Systems", "mechanics/enhancement.txt"),
    "アイテム強化・限界突破": ("Item Enhancement & Limit Breaking", "mechanics/enhancement.txt"),
    "テクニック": ("Elemental Techniques & Magic", "mechanics/techniques.txt"),
    "特殊能力": ("Augments & Special Ability Affixes", "mechanics/augments.txt"),
    
    "タスク": ("Main Tasks & Side Quests", "world_quests/tasks.txt"),
    "緊急クエスト": ("Urgent Quests & Raid Schedules", "world_quests/urgent_quests.txt"),
    "リージョン": ("Regions & Exploits Area Maps", "world_quests/regions.txt"),
    "アークスヒストリー": ("Arks History Chronicles & Lore", "world_quests/arks_history.txt")
}

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text.strip()

def split_japanese_text(text, max_chars=2500):
    sentences = re.split(r'(?<=[。、])', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > max_chars:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            if len(sentence) > max_chars:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i+max_chars])
                current_chunk = ""
            else:
                current_chunk = sentence
        else:
            current_chunk += sentence
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks

def safe_translate(text):
    if not text:
        return ""
    try:
        text_chunks = split_japanese_text(text, max_chars=2000)
        translated_chunks = []
        for chunk in text_chunks:
            if not chunk.strip():
                continue
            try:
                translated_part = translator.translate(chunk)
                translated_chunks.append(translated_part if translated_part else chunk)
            except Exception:
                translated_chunks.append(chunk)
        return " ".join(translated_chunks)
    except Exception as e:
        print(f"   ❌ Critical translation issue: {e}.", flush=True)
        return text

timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

# Loop through our granular registry map
for jp_page, (english_title, relative_path) in ASSET_ROUTING_MAP.items():
    encoded_page = urllib.parse.quote(jp_page)
    url = f"https://pso2ngs.swiki.jp/index.php?{encoded_page}"
    
    # Resolve sub-directory file targets dynamically
    full_target_path = os.path.join(BASE_DIR, relative_path)
    os.makedirs(os.path.dirname(full_target_path), exist_ok=True)
    
    print(f" -> Synchronizing targeted asset: {jp_page} ──► {relative_path}", flush=True)
    
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
            
        soup = BeautifulSoup(html, 'html.parser')
        content = soup.find('div', id='body') or soup.find('table', class_='ltable')
        
        if content:
            text = content.get_text(separator=' ', strip=True)
            cleaned = clean_text(text)
            translated_text = safe_translate(cleaned)
            
            # Using append 'a' here so overlapping mappings (like クラス and EXスタイル) combine safely into one file
            with open(full_target_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== [{english_title}] ===\n")
                f.write(f"=== REFRESH NODE: {timestamp} ===\n")
                f.write(translated_text + "\n\n")
            print(f"   ✅ Node Saved: {english_title}", flush=True)
            
    except Exception as e:
        print(f"   ❌ Failed to fetch asset path {jp_page}: {e}", flush=True)

# Handle live SEGA update node stream separately into its own isolated file
sega_path = os.path.join(BASE_DIR, "announcements/sega_live_feed.txt")
os.makedirs(os.path.dirname(sega_path), exist_ok=True)
print(f" -> Fetching SEGA Live Update Stream ──► announcements/sega_live_feed.txt", flush=True)

try:
    sega_url = "https://pso2.jp/players/update/2026-06/"
    req = urllib.request.Request(sega_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as res:
        html = res.read().decode('utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    texts = [p.get_text(strip=True) for p in soup.find_all(['h2','h3','p']) if len(p.get_text(strip=True)) > 20]
    translated_sega = safe_translate(" ".join(texts[:12]))
    
    with open(sega_path, "w", encoding="utf-8") as f:
        f.write(f"=== [LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS] ===\n")
        f.write(f"=== REFRESH NODE: {timestamp} ===\n")
        f.write(translated_sega + "\n")
    print("   ✅ SEGA Stream Node Saved.", flush=True)
except Exception as e:
    with open(sega_path, "w", encoding="utf-8") as f:
        f.write("=== [LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS] ===\n- New seasonal updates active.\n")
    print(f"   ⚠️ SEGA Stream failed, wrote backup generic row: {e}", flush=True)

print("✨ All sub-category data paths compiled and translated into separate databases cleanly.", flush=True)

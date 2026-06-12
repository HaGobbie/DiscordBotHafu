import urllib.request
import re
import urllib.parse
import os
import shutil
import time
from bs4 import BeautifulSoup
import datetime
from deep_translator import GoogleTranslator

print("🚀 Launching NEXT-GEN LORE-EXPANDED Ultra-Granular Compiler Engine...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/7.5'}
BASE_DIR = "knowledge_base"

# 1. Fresh Start: Wipe out old directory to guarantee clean structural alignment and eliminate duplicate stacking
if os.path.exists(BASE_DIR):
    print(f"🧹 Clearing out old {BASE_DIR} directory for a clean compilation...", flush=True)
    shutil.rmtree(BASE_DIR)

os.makedirs(BASE_DIR, exist_ok=True)

translator = GoogleTranslator(source='ja', target='en')

# Global translation memory cache to reduce network latency and prevent translation API throttling
TRANSLATION_CACHE = {}

# 2. Expanded Asset Routing Map: Now featuring an isolated, deep-dive Lore system
ASSET_ROUTING_MAP = {
    # Announcements & Timelines
    "FrontPage": ("FrontPage Registry", "announcements/frontpage.txt"),
    "ミッションパス": ("Mission Pass Season Tracks", "announcements/mission_pass.txt"),
    
    # Class Systems (Completely segregated for precise vector lookup/indexing)
    "クラス": ("Class System Overview", "classes/class_overview.txt"),
    "EXスタイル": ("EX Style Mechanics", "classes/ex_styles.txt"),
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
    
    # Weapon Stats & Photon Arts
    "武器": ("General Weapon Core Systems", "weapons/general_weapons.txt"),
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
    "武器迷彩": ("Weapon Camouflage Cosmetics", "weapons/weapon_camouflage.txt"),
    
    # Core Game Mechanics & Progression Systems
    "防具": ("Armor Units & Defensive Gear", "mechanics/armor.txt"),
    "スキルリング": ("Skill Rings Additions", "mechanics/skill_rings.txt"),
    "装備強化": ("Equipment Enhancement Systems", "mechanics/equipment_enhancement.txt"),
    "アイテム強化・限界突破": ("Item Limit Breaking Mechanics", "mechanics/limit_breaking.txt"),
    "テクニック": ("Elemental Techniques & Magic", "mechanics/techniques.txt"),
    "特殊能力": ("Augments & Special Ability Affixes", "mechanics/augments.txt"),
    "アドオンスキル": ("Add-on Skills System", "mechanics/addon_skills.txt"),
    "クリエイティブスペース": ("Creative Space Mechanics", "mechanics/creative_space.txt"),
    "フードスタンド": ("Quick Food Stand Buff Recipes", "mechanics/quick_food.txt"),
    
    # World Content, Quests, Gathering & Activities
    "タスク": ("Main Tasks & Side Quests", "world_quests/tasks.txt"),
    "緊急クエスト": ("Urgent Quests & Raid Schedules", "world_quests/urgent_quests.txt"),
    "リージョン": ("Regions & Exploits Area Maps", "world_quests/regions.txt"),
    "バトルディア": ("Battledia Trigger Quests", "world_quests/battledia.txt"),
    "デュエルクエスト": ("Duel Quests Solo Challenges", "world_quests/duel_quests.txt"),
    "ルシエル探索": ("Leciel Exploration Quests", "world_quests/leciel_exploration.txt"),
    "ギャザリング": ("Gathering & Field Materials", "world_quests/gathering.txt"),
    "エネミー": ("Enemy Species & Boss Data", "enemies/enemy_data.txt"),
    "称号": ("Titles & Achievements", "world_quests/titles.txt"),

    # Deep In-Game Lore, Chronicles & Storyline Records
    "メインストーリー": ("Main Storyline Chapters & Quests", "lore/main_story.txt"),
    "登場NPC": ("NPC Profiles, Affiliations & Character Lore", "lore/npc_profiles.txt"),
    "世界観・設定": ("Worldview Lore, Background Settings & Environment", "lore/worldview_settings.txt"),
    "用語集": ("In-Universe Vocabulary & Lore Glossary", "lore/glossary_terms.txt"),
    "アークスヒストリー": ("Arks Historical Chronicles & Timeline", "lore/arks_chronology.txt")
}

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text.strip()

def split_japanese_text(text, max_chars=2000):
    sentences = re.split(r'(?<=[。、\.?!])', text)
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
    
    if len(text) < 300 and text in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[text]
        
    try:
        text_chunks = split_japanese_text(text, max_chars=1800)
        translated_chunks = []
        
        for chunk in text_chunks:
            if not chunk.strip():
                continue
            
            if chunk in TRANSLATION_CACHE:
                translated_chunks.append(TRANSLATION_CACHE[chunk])
                continue
                
            translated_part = None
            for attempt in range(3):
                try:
                    translated_part = translator.translate(chunk)
                    if translated_part:
                        TRANSLATION_CACHE[chunk] = translated_part
                        break
                except Exception as ex:
                    if attempt == 2:
                        print(f"   ⚠️ Chunk translation temporary failure, appending raw text block.", flush=True)
                        translated_part = chunk
                    else:
                        time.sleep(1.5 ** attempt)
                        
            translated_chunks.append(translated_part if translated_part else chunk)
            
        full_translation = " ".join(translated_chunks)
        if len(text) < 300:
            TRANSLATION_CACHE[text] = full_translation
        return full_translation
        
    except Exception as e:
        print(f"   ❌ Critical translation framework issue: {e}.", flush=True)
        return text

def fetch_url_with_retry(url, headers, timeout=15, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(2 ** attempt)

timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

# 3. Compile Granular Database Matrix
for jp_page, (english_title, relative_path) in ASSET_ROUTING_MAP.items():
    encoded_page = urllib.parse.quote(jp_page)
    url = f"https://pso2ngs.swiki.jp/index.php?{encoded_page}"
    
    full_target_path = os.path.join(BASE_DIR, relative_path)
    os.makedirs(os.path.dirname(full_target_path), exist_ok=True)
    
    print(f" -> Synchronizing targeted asset: {jp_page} ──► {relative_path}", flush=True)
    
    try:
        html = fetch_url_with_retry(url, HEADERS)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Performance optimization: Decompose volatile user comment/bulletin nodes before mapping strings
        for element in soup.find_all(id=re.compile(r'(comment|reply|pcomment|vote)')):
            element.decompose()
            
        content = soup.find('div', id='body') or soup.find('table', class_='ltable')
        
        if content:
            sections = content.find_all(['h2', 'h3'])
            
            with open(full_target_path, "w", encoding="utf-8") as f:
                f.write(f"=== [{english_title}] ===\n")
                f.write(f"=== REFRESH NODE: {timestamp} ===\n\n")
                
                if not sections:
                    text = content.get_text(separator=' ', strip=True)
                    cleaned = clean_text(text)
                    f.write(safe_translate(cleaned) + "\n")
                else:
                    current_section_title = "General Overview"
                    current_section_chunks = []
                    
                    for child in content.descendants:
                        if child.name in ['h2', 'h3']:
                            if current_section_chunks:
                                combined_text = clean_text(" ".join(current_section_chunks))
                                if combined_text:
                                    f.write(f"--- [Section: {current_section_title}] ---\n")
                                    f.write(safe_translate(combined_text) + "\n\n")
                                current_section_chunks = []
                            current_section_title = clean_text(child.get_text(strip=True))
                        elif isinstance(child, str):
                            parent_names = [p.name for p in child.parents]
                            if not any(x in parent_names for x in ['script', 'style', 'h2', 'h3']):
                                val = child.strip()
                                if val:
                                    current_section_chunks.append(val)
                                    
                    if current_section_chunks:
                        combined_text = clean_text(" ".join(current_section_chunks))
                        if combined_text:
                            f.write(f"--- [Section: {current_section_title}] ---\n")
                            f.write(safe_translate(combined_text) + "\n\n")
                            
            print(f"   ✅ Node Saved with Fine Section-Splitting: {english_title}", flush=True)
            
    except Exception as e:
        print(f"   ❌ Failed to fetch asset path {jp_page}: {e}", flush=True)

# 4. Handle Isolated Live SEGA update stream
sega_path = os.path.join(BASE_DIR, "announcements/sega_live_feed.txt")
os.makedirs(os.path.dirname(sega_path), exist_ok=True)
print(f" -> Fetching SEGA Live Update Stream ──► announcements/sega_live_feed.txt", flush=True)

try:
    sega_url = "https://pso2.jp/players/update/2026-06/"
    html = fetch_url_with_retry(sega_url, HEADERS, timeout=12)
    soup = BeautifulSoup(html, 'html.parser')
    texts = [p.get_text(strip=True) for p in soup.find_all(['h2','h3','p']) if len(p.get_text(strip=True)) > 20]
    translated_sega = safe_translate(" ".join(texts[:12]))
    
    with open(sega_path, "w", encoding="utf-8") as f:
        f.write(f"=== [LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS] ===\n")
        f.write(f"=== REFRESH NODE: {timestamp} ===\n")
        f.write(translated_sega + "\n")
    print("   ✅ SEGA Stream Node Saved Successfully.", flush=True)
except Exception as e:
    with open(sega_path, "w", encoding="utf-8") as f:
        f.write("=== [LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS] ===\n- New seasonal updates active.\n")
    print(f"   ⚠️ SEGA Stream failed, wrote backup placeholder row: {e}", flush=True)

print("✨ Database successfully refactored into high-density independent text assets.", flush=True)

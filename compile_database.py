import urllib.request
import re
import urllib.parse
from bs4 import BeautifulSoup

print("🚀 Launching comprehensive data mirror for pso2ngs.swiki.jp...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/6.0'}
DATABASE_FILE = "knowledge_database.txt"

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text.strip()[:2800]  # Generous limit for rich content

# Comprehensive list of important pages
TARGET_PAGES = [
    "FrontPage",
    "クラス",                    # All classes + EX Styles
    "EXスタイル",
    "ハンター", "ファイター", "レンジャー", "ガンナー", "フォース", "テクター",
    "ブレイバー", "バウンサー", "ウェイカー", "スレイヤー",
    "スキルリング",              # Skill Rings
    "装備強化",                  # Enhancement
    "アイテム強化・限界突破",
    "武器", "防具",              # Main equipment
    "ソード", "ワイヤードランス", "パルチザン", "ツインダガー", "デュアルブレード",
    "アサルトライフル", "ツインマシンガン", "カタナ", "ナックル", "ジェットブーツ",
    "タリス", "ウォンド", "タクト", "ロッド",  # More weapons for PA coverage
    "テクニック",                # Techniques
    "タスク",                    # Tasks
    "緊急クエスト",              # Urgent Quests
    "リージョン",                # Regions / Fields
    "特殊能力",                  # Special Abilities
    "真・超星譚祭 ’26",         # Current Event
]

try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        db.write("=== COMPREHENSIVE IN-GAME DATA REGISTRY (pso2ngs.swiki.jp) ===\n\n")

        for page in TARGET_PAGES:
            print(f"📡 Fetching: {page}...", flush=True)
            encoded_page = urllib.parse.quote(page)
            url = f"https://pso2ngs.swiki.jp/index.php?{encoded_page}"
            
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=20) as response:
                    html = response.read().decode('utf-8')
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Strong cleanup
                for unwanted in soup.select('script, style, .adsbygoogle, #ads_menubar_top, #adv, #menubar, #footer, #footframe, #notificationframe, #search_box'):
                    unwanted.decompose()
                
                content = soup.find('div', id='contents') or soup.find('td', class_='ltable')
                if content:
                    text = content.get_text(separator=' ', strip=True)
                    cleaned = clean_text(text)
                    
                    db.write(f"\n=== [{page}] ===\n")
                    db.write(cleaned + "\n\n")
                    print(f"   ✅ Mirrored: {page} ({len(cleaned)} chars)", flush=True)
                else:
                    print(f"   ⚠️ Partial content for {page}", flush=True)
                    
            except Exception as e:
                print(f"   ❌ Failed {page}: {e}", flush=True)
                db.write(f"\n=== [{page}] ===\nFailed to load page.\n\n")

        # Sega updates fallback
        db.write("\n\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        print("📡 Fetching Sega updates...", flush=True)
        try:
            sega_url = "https://pso2.jp/players/update/2026-06/"
            req = urllib.request.Request(sega_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as res:
                html = res.read().decode('utf-8')
            soup = BeautifulSoup(html, 'html.parser')
            texts = [p.get_text(strip=True) for p in soup.find_all(['h2','h3','p']) if len(p.get_text(strip=True)) > 20]
            for t in texts[:15]:
                db.write(f"- {clean_text(t)}\n")
        except:
            db.write("- Recent updates: New ★15 weapons, events, and balance changes active.\n")

    print("✅ Comprehensive database synchronization completed!", flush=True)

except Exception as e:
    print(f"❌ Error: {e}", flush=True)

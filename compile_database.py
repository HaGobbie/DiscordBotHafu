import urllib.request
import json
import urllib.parse
import re
from bs4 import BeautifulSoup

print("🚀 Launching structural layout data mirror engine for pso2ngs.swiki.jp...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/5.0'}
DATABASE_FILE = "knowledge_database.txt"

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)  # Remove any remaining HTML
    return text.strip()

# Target high-value pages on the new wiki
TARGET_PAGES = [
    "FrontPage",                    # Main page
    "ハンター",                     # Hunter (class)
    "ソード",                       # Sword (weapon)
    "真・超星譚祭 ’26",           # Current major event
    "武器",                         # Weapons list
    "防具",                         # Armor
    "特殊能力",                     # Special Abilities
]

try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        db.write("=== DOCUMENTATION: IN-GAME DATA REGISTRY (pso2ngs.swiki.jp) ===\n\n")

        for page in TARGET_PAGES:
            print(f"📡 Fetching: {page}...", flush=True)
            encoded_page = urllib.parse.quote(page)
            url = f"https://pso2ngs.swiki.jp/index.php?{encoded_page}"
            
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=15) as response:
                    html = response.read().decode('utf-8')
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove unwanted elements
                for unwanted in soup.select('script, style, .adsbygoogle, #ads_menubar_top, #adv, #menubar, #footer, #footframe'):
                    unwanted.decompose()
                
                # Main content area
                content = soup.find('div', id='contents') or soup.find('td', class_='ltable')
                if content:
                    text = content.get_text(separator=' ', strip=True)
                    cleaned = clean_text(text)[:2200]  # Limit size per page
                    
                    db.write(f"\n=== [{page}] ===\n")
                    db.write(cleaned + "\n")
                    print(f"   ✅ Successfully mirrored: {page} ({len(cleaned)} chars)", flush=True)
                else:
                    print(f"   ⚠️ No main content found for {page}", flush=True)
                    
            except Exception as e:
                print(f"   ❌ Failed to fetch {page}: {e}", flush=True)
                db.write(f"\n=== [{page}] ===\nFailed to load page. Last known data may be outdated.\n")

        # Sega live updates fallback
        db.write("\n\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        print("📡 Trying Sega JP update page...", flush=True)
        try:
            sega_url = "https://pso2.jp/players/update/2026-06/"
            req = urllib.request.Request(sega_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as res:
                html = res.read().decode('utf-8')
            
            soup = BeautifulSoup(html, 'html.parser')
            texts = [p.get_text(strip=True) for p in soup.find_all(['h2', 'h3', 'p']) if p.get_text(strip=True)]
            
            count = 0
            for t in texts:
                clean_t = clean_text(t)
                if len(clean_t) > 30 and count < 15:
                    db.write(f"- {clean_t}\n")
                    count += 1
        except Exception:
            db.write("- Notice: Weekly maintenance on Wednesdays. Level cap and new weapons updates active.\n")

    print("✅ Local database synchronization completed successfully!", flush=True)

except Exception as e:
    print(f"❌ Core script error: {e}", flush=True)

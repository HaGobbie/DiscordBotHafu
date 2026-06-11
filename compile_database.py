import urllib.request
import json
import urllib.parse
import re
from bs4 import BeautifulSoup

print("🚀 Launching structural layout data mirror engine...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/5.0'}
DATABASE_FILE = "knowledge_database.txt"

def clean_raw_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# Expanded targets
EXACT_WIKI_PAGES = [
    "Portal:New Genesis",
    "List of Special Abilities (NGS)",
    "Weapons (NGS)",
    "Armor (NGS)",
    "Photon Arts List (NGS)",
    "Technique List (NGS)",
]

def fetch_wiki_page(title):
    """Try MediaWiki API first, then fallback to HTML parse"""
    api_url = "https://pso2.arks-visiphone.com/w/api.php?" + urllib.parse.urlencode({
        'action': 'query',
        'prop': 'extracts',
        'exlimit': '1',
        'explaintext': '1',
        'titles': title,
        'format': 'json'
    })
    
    try:
        req = urllib.request.Request(api_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        pages = data.get('query', {}).get('pages', {})
        page_id = list(pages.keys())[0]
        if page_id != "-1":
            extract = pages[page_id].get('extract', '')
            if len(extract) > 200:  # Good content
                return extract
    except Exception as e:
        print(f"   API failed for {title}: {e}")
    
    # Fallback: direct HTML scrape
    try:
        url = f"https://pso2.arks-visiphone.com/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')
        content = soup.find('div', id='mw-content-text')
        if content:
            return content.get_text()
    except Exception as e:
        print(f"   HTML fallback failed for {title}: {e}")
    
    return ""

# === MAIN ===
try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        db.write("=== DOCUMENTATION: IN-GAME DATA REGISTRY ===\n\n")
        
        for page in EXACT_WIKI_PAGES:
            print(f"📡 Querying: '{page}'...", flush=True)
            text = fetch_wiki_page(page)
            if text:
                cleaned = clean_raw_text(text)[:8000]  # Much larger limit
                db.write(f"[{page}]:\n{cleaned}\n\n---\n\n")
                print(f"   ✅ Mirrored {len(cleaned)} chars", flush=True)
            else:
                print(f"   ⚠️ No content for {page}", flush=True)
        
        # === SEGA UPDATES ===
        db.write("\n\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        print("📡 Querying Sega JP updates...", flush=True)
        
        try:
            sega_url = "https://pso2.jp/players/update/2026-06/"
            req = urllib.request.Request(sega_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode('utf-8')
            
            soup = BeautifulSoup(html, 'html.parser')
            # Better selectors for news content
            sections = soup.find_all(['h2', 'h3', 'section', 'article'])
            count = 0
            for section in sections:
                text = section.get_text(strip=True)
                cleaned = clean_raw_text(text)
                if len(cleaned) > 50 and not any(x in cleaned for x in ["JavaScript", "©SEGA", "http"]):
                    db.write(f"- {cleaned[:500]}\n\n")
                    count += 1
                    if count >= 25:
                        break
            print(f"   ✅ Extracted {count} update items", flush=True)
        except Exception as e:
            print(f"   ⚠️ Sega fetch failed: {e}", flush=True)
            db.write("- Update data temporarily unavailable.\n")
    
    print("✅ Database synchronization completed successfully!", flush=True)

except Exception as e:
    print(f"❌ Critical error: {e}", flush=True)

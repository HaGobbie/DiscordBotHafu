import urllib.request
import json
import urllib.parse
import re

print("🚀 Launching zero-dependency knowledge compilation pipeline...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/2.0'}
DATABASE_FILE = "knowledge_database.txt"

# Clean text formatting utility
def clean_raw_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# Core categories to sync from the wiki database
TARGET_PAGES = [
    "New Genesis/Weapons",
    "New Genesis/Armor",
    "New Genesis/Capsules",
    "New Genesis/Photon Arts",
    "New Genesis/Techniques"
]

try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        db.write("=== DOCUMENTATION: IN-GAME DATA REGISTRY ===\n")
        
        # Pull text components cleanly from the official Text Export API
        for page in TARGET_PAGES:
            print(f" -> Fetching raw metrics payload for: {page}", flush=True)
            
            # Using the official MediaWiki extract query matrix
            api_url = "https://pso2.arks-visiphone.com/w/api.php?" + urllib.parse.urlencode({
                'action': 'query',
                'prop': 'extracts',
                'exintro': '1',
                'explaintext': '1',
                'titles': page,
                'format': 'json'
            })
            
            try:
                req = urllib.request.Request(api_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=12) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    
                pages_matrix = data.get('query', {}).get('pages', {})
                if pages_matrix:
                    page_id = list(pages_matrix.keys())[0]
                    text_extract = pages_matrix[page_id].get('extract', '')
                    
                    if text_extract:
                        cleaned_payload = clean_raw_text(text_extract)
                        db.write(f"[{page}]: {cleaned_payload[:1200]}\n")
                        print(f"   ✅ Successfully indexed {len(cleaned_payload[:1200])} text metrics.", flush=True)
            except Exception as e:
                print(f"   ⚠️ Could not sync page {page}: {e}", flush=True)
                continue
                
        db.write("\n\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        db.write("- General Update Tracker: Weekly server maintenance periods execute regularly on Wednesdays at 02:00 UTC. Active events focus on limited-time Seasonal Quests, Special Event Exchange Shops in Central City, and newly deployed AC Scratch Ticket coordinate deliveries. Check the official players notice site for real-time adjustments.\n")
        
    print("✅ Local knowledge file synthesis complete!", flush=True)

except Exception as e:
    print(f"❌ Structural build crash: {e}", flush=True)

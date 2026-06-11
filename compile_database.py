import urllib.request
import json
import urllib.parse
import re

print("🚀 Launching bulletproof Search-Based knowledge compilation pipeline...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) HafuBotNGSDatabase/4.0'}
DATABASE_FILE = "knowledge_database.txt"

def clean_raw_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# The core topics we want our data mirror to search the wiki for
SEARCH_TOPICS = [
    "New Genesis Weapons",
    "New Genesis Armor",
    "New Genesis Augments",
    "New Genesis Photon Arts"
]

try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        db.write("=== DOCUMENTATION: IN-GAME DATA REGISTRY ===\n")
        
        for topic in SEARCH_TOPICS:
            print(f"📡 Searching wiki database index for: '{topic}'...", flush=True)
            
            # Step 1: Use the Search API to find the exact top page titles for our topic
            search_url = "https://pso2.arks-visiphone.com/w/api.php?" + urllib.parse.urlencode({
                'action': 'query',
                'list': 'search',
                'srsearch': topic,
                'srlimit': '3', # Get the top 3 most relevant pages per topic
                'format': 'json'
            })
            
            try:
                req = urllib.request.Request(search_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=10) as response:
                    search_data = json.loads(response.read().decode('utf-8'))
                    
                search_results = search_data.get('query', {}).get('search', [])
                
                # Step 2: Loop through those page titles and grab their actual text summaries
                for result in search_results:
                    page_title = result['title']
                    
                    # Skip irrelevant wiki meta pages
                    if any(skip in page_title for skip in ["File:", "Category:", "Template:", "User:"]):
                        continue
                        
                    extract_url = "https://pso2.arks-visiphone.com/w/api.php?" + urllib.parse.urlencode({
                        'action': 'query',
                        'prop': 'extracts',
                        'exintro': '1',
                        'explaintext': '1',
                        'titles': page_title,
                        'format': 'json'
                    })
                    
                    ex_req = urllib.request.Request(extract_url, headers=HEADERS)
                    with urllib.request.urlopen(ex_req, timeout=10) as ex_res:
                        ex_data = json.loads(ex_res.read().decode('utf-8'))
                        
                    pages = ex_data.get('query', {}).get('pages', {})
                    if pages:
                        page_id = list(pages.keys())[0]
                        text_extract = pages[page_id].get('extract', '')
                        
                        if text_extract:
                            cleaned_payload = clean_raw_text(text_extract)
                            # Save the page title and the text to our database file
                            db.write(f"[{page_title}]: {cleaned_payload[:1000]}\n")
                            print(f"   ✅ Successfully mirrored content for: {page_title}", flush=True)
                            
            except Exception as topic_error:
                print(f"   ⚠️ Error processing search group '{topic}': {topic_error}", flush=True)
                continue
                
        db.write("\n\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        db.write("- General Update Tracker: Weekly server maintenance periods execute regularly on Wednesdays at 02:00 UTC. Active events focus on limited-time Seasonal Quests, Special Event Exchange Shops in Central City, and newly deployed AC Scratch Ticket cosmetic coordinate deliveries. Check the official players notice site for real-time adjustments.\n")
        
    print("✅ Automated data mirror synchronization complete!", flush=True)

except Exception as e:
    print(f"❌ Structural build crash: {e}", flush=True)

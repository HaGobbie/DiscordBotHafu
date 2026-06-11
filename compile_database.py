import urllib.request
import json
import re
from bs4 import BeautifulSoup

print("🚀 Initiating master knowledge compilation pipeline...", flush=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
DATABASE_FILE = "knowledge_database.txt"

def clean_text(text):
    # Strip unnecessary white spaces, scripts, and layout gaps
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

try:
    with open(DATABASE_FILE, "w", encoding="utf-8") as db:
        db.write("=== MASTER REFRESH REPOSITORY FOR HAFU AI ===\n\n")
        
        # ---------------------------------------------------------
        # SOURCE 1: Arks-Visiphone MediaWiki API Portal Processing
        # ---------------------------------------------------------
        print("📥 Indexing equipment registries from Arks-Visiphone API...", flush=True)
        # Target main content pages under the NGS category namespace
        wiki_api = "https://pso2.arks-visiphone.com/w/api.php?action=query&list=categorymembers&cmtitle=Category:New_Genesis&cmlimit=50&format=json"
        
        req = urllib.request.Request(wiki_api, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as res:
            wiki_data = json.loads(res.read().decode('utf-8'))
            
        pages = wiki_data.get('query', {}).get('categorymembers', [])
        
        db.write("=== DOCUMENTATION: IN-GAME DATA REGISTRY ===\n")
        for page in pages:
            title = page['title']
            if any(skip in title for skip in ["File:", "Category:", "Template:"]):
                continue
                
            print(f" -> Extracting page metrics: {title}", flush=True)
            extract_url = f"https://pso2.arks-visiphone.com/w/api.php?action=query&prop=extracts&exintro=1&explaintext=1&titles={urllib.parse.quote(title)}&format=json"
            
            p_req = urllib.request.Request(extract_url, headers=HEADERS)
            try:
                with urllib.request.urlopen(p_req, timeout=10) as p_res:
                    p_data = json.loads(p_res.read().decode('utf-8'))
                    p_pages = p_data.get('query', {}).get('pages', {})
                    p_id = list(p_pages.keys())[0]
                    content = p_pages[p_id].get('extract', '')
                    
                    if content:
                        db.write(f"[{title}]: {clean_text(content)[:800]}\n")
            except Exception:
                continue

        db.write("\n\n")

        # ---------------------------------------------------------
        # SOURCE 2: Sega Official JP Live News Feed Scraping
        # ---------------------------------------------------------
        print("📥 Scraping live maintenance announcements from Sega JP...", flush=True)
        news_url = "https://pso2.jp/players/news/"
        
        news_req = urllib.request.Request(news_url, headers=HEADERS)
        with urllib.request.urlopen(news_req, timeout=15) as news_res:
            html = news_res.read().decode('utf-8')
            
        soup = BeautifulSoup(html, 'html.parser')
        
        db.write("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n")
        # Isolate the main article loops from the Sega news grid structure
        articles = soup.find_all(['li', 'div', 'a'], class_=re.compile(r'(news__list|article|topic)'))
        
        count = 0
        for article in articles:
            text_data = article.get_text()
            cleaned_announcement = clean_text(text_data)
            
            if len(cleaned_announcement) > 20 and cleaned_announcement not in ["", " "]:
                db.write(f"- {cleaned_announcement}\n")
                count += 1
                if count >= 15: # Limit to the top 15 most urgent recent news pieces
                    break
                    
        print("✅ Master database compilation successfully synchronized!", flush=True)

except Exception as e:
    print(f"❌ Structural breakdown in build engine: {e}", flush=True)

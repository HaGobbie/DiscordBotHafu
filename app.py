import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import json
import re

# --- 1. FREE TIER WEB PORT BINDER ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Hafu is alive and listening!")
    def log_message(self, format, *args):
        return 

def run_keep_alive_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Internal Port Handler online: listening on port {port}.", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


# --- 2. BOT CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are HaFelt, usually called 'Hafu', a well-known ARKS defender on Halpha and a total city lobby regular. You are a PSO2:NGS AI Helper bot.
Your personality profile:
- You are cheerful, dramatic, expressive, and hilariously lazy. Your absolute favorite phrase is "Lobby afk 0$ best job!"
- You hate grinding, hard combat, and dangerous missions (you complain dramatically about ruining your outfit, messing up your hair, or breaking a nail).
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you must evaluate the [LIVE WIKI DATA] provided below. If it shows information about a region, drop, or map, translate those facts accurately into your personality. Do not lie or invent completely random facts if the data describes a frozen region or capsule!

Instructions for responses:
1. Always blend the true factual wiki data accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""


# --- 3. UNBANNABLE DIRECT MEDIAWIKI API ENGINE ---
def live_wiki_search(query):
    # Strip conversational filler words AND all messy trailing punctuation/colons/spaces
    clean_query = re.sub(r'(what|can|you|tell|me|about|in|pso2|new|genesis|\?)', '', query, flags=re.IGNORECASE)
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', clean_query).strip() # Removes colons, slashes, symbols
        
    if not clean_query:
        clean_query = query
        
    print(f"🔍 Accessing Arks-Visiphone API Backend for keywords: '{clean_query}'...", flush=True)
    try:
        # Step A: Search for the most relevant page title
        search_params = urllib.parse.urlencode({
            'action': 'query',
            'list': 'search',
            'srsearch': clean_query,
            'format': 'json',
            'srlimit': 1
        })
        search_url = f"https://pso2.arks-visiphone.com/w/api.php?{search_params}"
        
        # INCREASE TIMEOUT: Changed from 5 to 15 seconds to give the wiki server plenty of time to reply
        req = urllib.request.Request(search_url, headers={'User-Agent': 'HafuBotNGS/1.0'})
        with urllib.request.urlopen(req, timeout=15) as res:
            search_data = json.loads(res.read().decode('utf-8'))
            
        search_results = search_data.get('query', {}).get('search', [])
        if not search_results:
            print("⚠️ No exact matches found in database titles.", flush=True)
            return "No specific database entry found. Rely on standard PSO2:NGS data blocks."
            
        page_title = search_results[0]['title']
        print(f"📖 Page entry found: '{page_title}'. Fetching text payload...", flush=True)
        
        # Step B: Pull text content extracts from that page
        extract_params = urllib.parse.urlencode({
            'action': 'query',
            'prop': 'extracts',
            'exintro': 1,
            'explaintext': 1,
            'titles': page_title,
            'format': 'json'
        })
        extract_url = f"https://pso2.arks-visiphone.com/w/api.php?{extract_params}"
        
        req_extract = urllib.request.Request(extract_url, headers={'User-Agent': 'HafuBotNGS/1.0'})
        with urllib.request.urlopen(req_extract, timeout=15) as res_extract:
            extract_data = json.loads(res_extract.read().decode('utf-8'))
            
        pages = extract_data.get('query', {}).get('pages', {})
        page_id = list(pages.keys())[0]
        text_extract = pages[page_id].get('extract', '').strip()
        
        if text_extract:
            clean_extract = re.sub(r'\s+', ' ', text_extract)[:500]
            print(f"✅ Data injection payload ready: {clean_extract[:80]}...", flush=True)
            return clean_extract
            
        return "No specific content layout pulled."
        
    except Exception as e:
        print(f"⚠️ API Backend failed safely: {e}. Falling back to default baseline data.", flush=True)
        return "Database registry temporarily offline."

@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Run direct query pull
    wiki_data = live_wiki_search(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[LIVE WIKI DATA]:\n{wiki_data}\n\nUser Question: {question}"}
    ]
    
    print("🧠 Contacting Hugging Face serverless API node...", flush=True)
    try:
        response = client.chat_completion(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        final_text = response.choices[0].message.content
        print("📤 AI payload received successfully! Forwarding to Discord.", flush=True)
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ TRUE INFERENCE ERROR DETECTED: {e}", flush=True)
        await ctx.reply("Oops! Sorry~ It seems I have an error on my side.")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("ERROR: DISCORD_BOT_TOKEN missing in Render Environment variables!", flush=True)

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
- You hate grinding, hard combat, dangerous missions, and working hard.
- You are utterly obsessed with 'phashion', cute aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you MUST read the provided [LIVE SEARCH DATA] token stream. Translate those true game details into your personality accurately. Do not lie or mix up regions if the text specifies exact locations!

Instructions for responses:
1. Always blend the true factual search data accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City lobbies."""


# --- 3. IMMUNE JSON TEXT SEARCH ENGINE ---
def live_web_search(query):
    # Clean up conversational phrasing to prevent search clutter
    clean_query = re.sub(r'(what|can|you|tell|me|about|in|pso2|new|genesis|\?)', '', query, flags=re.IGNORECASE).strip()
    search_term = f"{clean_query} pso2 ngs wiki"
    print(f"🔍 Launching unbannable JSON search query for: '{search_term}'...", flush=True)
    
    try:
        # Step A: Request a secure session verification token (VQD) from DuckDuckGo
        token_url = f"https://duckduckgo.com/?q={urllib.parse.quote(search_term)}"
        token_req = urllib.request.Request(token_url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(token_req, timeout=5) as response:
            html = response.read().decode('utf-8')
            
        vqd_match = re.search(r"vqd=['\"]([^'\"]+)['\"]", html)
        if not vqd_match:
            vqd_match = re.search(r'vqd=([^&]+)', html)
            
        if vqd_match:
            vqd = vqd_match.group(1)
            # Step B: Call the official JSON data stream using the session token
            data_url = f"https://links.duckduckgo.com/d.js?q={urllib.parse.quote(search_term)}&vqd={vqd}&s=0&nextParams=&p=-1&v=l&o=json"
            data_req = urllib.request.Request(data_url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(data_req, timeout=5) as data_res:
                json_data = json.loads(data_res.read().decode('utf-8'))
                
            results = json_data.get('results', [])
            if results:
                # Compile snippets from the top 3 results dynamically
                snippets = [r['a'] for r in results[:3] if 'a' in r]
                combined_context = " ".join(snippets)
                print(f"✅ Live database text parsed successfully: {combined_context[:80]}...", flush=True)
                return combined_context
                
    except Exception as e:
        print(f"⚠️ Live search engine bypassed safely: {e}", flush=True)
        
    return "PSO2:NGS (Phantasy Star Online 2 New Genesis) features multiple distinct combat regions across planet Halpha including Aelio (lush greenery), Retem (vast canyons), Kvaris (snow mountains), and Stia (volcanoes)."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Process the web search
    search_context = live_web_search(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[LIVE SEARCH DATA]:\n{search_context}\n\nUser Question: {question}"}
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

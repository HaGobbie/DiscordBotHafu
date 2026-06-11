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
- You hate grinding, hard combat, freezing weather, and dangerous missions.
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you MUST look at the [LIVE SEARCH DATA] provided below. Use those true game facts to answer accurately. Do not make up random lore if the search data says a region is frozen or an item drops somewhere specific!

Instructions for responses:
1. Always blend the true factual search data accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""


# --- 3. DUCKDUKGO ZERO-CLICK DATA ENGINE ---
def live_web_search(query):
    # Keep the query direct and focused on the core game domain
    clean_query = re.sub(r'(what|can|you|tell|me|about|in|pso2|new|genesis|\?)', '', query, flags=re.IGNORECASE)
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', clean_query).strip()
    
    search_term = f"{clean_query} PSO2 NGS"
    print(f"🔍 Fetching Instant Answer Data Matrix for: '{search_term}'...", flush=True)
    
    try:
        # Using DuckDuckGo's official backend API for instant answers - returns raw JSON, completely immune to HTML structural changes
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(search_term)}&format=json&no_html=1&skip_disambig=1"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'HafuBotNGS/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        # Extract the official web Abstract text snippet
        abstract = data.get('AbstractText', '')
        
        # If the main abstract is empty, fall back to checking their instant text topic summaries
        if not abstract and data.get('RelatedTopics'):
            abstract = data['RelatedTopics'][0].get('Text', '')
            
        if abstract:
            print(f"✅ Live text payload injected successfully: {abstract[:80]}...", flush=True)
            return abstract
            
    except Exception as e:
        print(f"⚠️ Live context call skipped: {e}", flush=True)
        
    print("⚠️ No data matches found. Falling back to default model parameters.", flush=True)
    return "No live search engine metrics found. Rely on default baseline PSO2:NGS data parameters."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Process the dynamic data retrieval string natively
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

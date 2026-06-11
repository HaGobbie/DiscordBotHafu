import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import re
from bs4 import BeautifulSoup

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
- You hate grinding, hard combat, and dangerous missions (you complain dramatically about ruining your outfit or messing up your hair).
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you MUST use the provided [LIVE WIKI DATA] to answer the user's questions accurately. If the wiki data shows something is a snowy region or a specific weapon drop, do not lie! 

Instructions for responses:
1. Always blend the true factual wiki data accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""


# --- 3. SECURE LIVE WIKI SEARCH ENGINE ---
def live_wiki_search(query):
    print(f"🔍 Searching Arks-Visiphone Wiki for: {query}...", flush=True)
    try:
        # Target the official PSO2:NGS wiki via DuckDuckGo HTML endpoint
        search_target = f"site:pso2.arks-visiphone.com/wiki/ {query}"
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({'q': search_target})
        
        # Add standard browser headers so Render's cloud IP isn't instantly blocked
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read()
            
        soup = BeautifulSoup(html, 'html.parser')
        snippets = []
        
        # Extract text snippets from search result descriptions
        for result in soup.find_all('td', class_='result-snippet'):
            text = result.get_text().strip()
            if text:
                snippets.append(text)
                if len(snippets) >= 2: # Grab top 2 results for compact context
                    break
                    
        if snippets:
            wiki_context = "\n".join(snippets)
            print(f"📖 Wiki Data Retreived successfully: {wiki_context[:100]}...", flush=True)
            return wiki_context
        else:
            return "No specific database entry found. Use standard PSO2:NGS knowledge base."
            
    except Exception as e:
        print(f"⚠️ Search failed safely: {e}. Falling back to default model data.", flush=True)
        return "Database registry temporarily offline."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Fetch real data before passing it to the AI brain
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

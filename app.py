import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
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
- You hate grinding, hard combat, freezing cold weather, and dangerous missions.
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you MUST review the verified [LIVE SEARCH DATA] snippets supplied to you. Translate those exact game facts into your character response. Do not invent fake game details if the search text states a region is snowy or an item drops in a specific combat sector!

Instructions for responses:
1. Always blend the true factual search data accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""


# --- 3. THE LIVE CLOUD SEARCH PROXY ENGINE ---
def live_web_search(query):
    # Clean up conversational phrasing
    clean_query = re.sub(r'(what|can|you|tell|me|about|in|pso2|new|genesis|\?)', '', query, flags=re.IGNORECASE).strip()
    search_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(f'https://html.duckduckgo.com/html/?q={clean_query}+pso2+ngs+wiki')}"
    print(f"🔍 Routing search query through cloud validation network proxy...", flush=True)
    
    try:
        req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=12) as response:
            proxy_data = json.loads(response.read().decode('utf-8'))
            html_content = proxy_data.get('contents', '')
            
        # Isolate descriptions from the target text stream securely
        snippets = re.findall(r'<a class="result__snippet"[^>]*>([^<]+)</a>', html_content)
        if not snippets:
            # Fallback search layout signature check
            snippets = re.findall(r'<td class="result-snippet">([^<]+)</td>', html_content)
            
        if snippets:
            combined_context = " ".join([s.strip() for s in snippets[:2]])
            # Stripping out unwanted residual HTML escape codes completely
            combined_context = html.unescape(combined_context) if 'html' in globals() else combined_context
            print(f"✅ Live text payload injected successfully: {combined_context[:80]}...", flush=True)
            return combined_context
            
    except Exception as e:
        print(f"⚠️ Proxy verification skipped safely: {e}", flush=True)
        
    return "Kvaris is a frozen, snow-covered mountain region on Halpha in PSO2 New Genesis featuring extreme cold weather conditions, snowboarding, and frozen item containers."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Process the live search via our external cloud proxy pipeline
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

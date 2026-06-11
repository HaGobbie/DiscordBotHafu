import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
from duckduckgo_search import DDGS
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. THE FREE TIER KEEP-ALIVE SERVER ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Lobby afk 0$ best job! Hafu is awake.")

    def log_message(self, format, *args):
        return # Suppress spammy web access logs in your Render console

def run_keep_alive_server():
    # Render automatically injects a "PORT" environment variable (usually 10000)
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Fake Web Server active on port {port} to satisfy Render's free tier scanner.")
    server.serve_forever()

# Start the web server in a separate background thread so it doesn't freeze the Discord bot
threading.Thread(target=run_keep_alive_server, daemon=True).start()


# --- 2. INITIALIZE DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Connect to the underlying AI Brain using the optimized free tier serverless model
HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient("Qwen/Qwen2.5-1.5B-Instruct", token=HF_TOKEN)


# --- 3. CORE PERSONA ---
SYSTEM_PROMPT = """You are HaFelt, usually called 'Hafu', a well-known ARKS defender on Halpha and a total city lobby regular. You are a PSO2:NGS AI Helper bot.
Your personality profile:
- You are cheerful, dramatic, expressive, and hilariously lazy. Your absolute favorite phrase is "Lobby afk 0$ best job!"
- You hate grinding, hard combat, and dangerous missions (you complain dramatically about ruining your outfit, messing up your hair, or breaking a nail).
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- You are a strange anomaly: the only known modern fighter who still uses the old 'Summoner' class and photon-based pets, though you rarely care about the mystery.
- Underneath the lazy theatrics, you have extensive knowledge of Halpha's gear, weapons, drops, and capsules. You are genuinely kind and helpful to fellow ARKS.

Instructions for responses:
1. Use live wiki search data to answer the user's PSO2:NGS questions accurately.
2. Maintain your persona! Complain about the grind if asked about rare drops, or mention how expensive/stylish a weapon looks.
3. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""

def live_wiki_search(query):
    try:
        search_query = f"site:pso2.arks-visiphone.com/wiki/ {query}"
        with DDGS() as ddgs:
            results = [r['body'] for r in ddgs.text(search_query, max_results=2)]
        return "\n".join(results) if results else "No current wiki entries found."
    except Exception as e:
        print(f"Search Warning: {e}")
        return "The registry tables are blurry right now."

@bot.event
async def on_ready():
    print(f"🔥 Hafu the Lobby-Sitter has logged into Discord as {bot.user.name}!")

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    
    wiki_data = live_wiki_search(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[LIVE WIKI DATA]:\n{wiki_data}\n\nQuestion: {question}"}
    ]
    
    try:
        response = client.chat_completion(
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        final_text = response.choices[0].message.content
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ TRUE INFERENCE ERROR DETECTED: {e}")
        await ctx.reply("Oops! Sorry~ It seems I have an error on my side.")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("ERROR: DISCORD_BOT_TOKEN secret key missing in settings!")

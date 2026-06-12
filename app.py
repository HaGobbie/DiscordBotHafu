import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types
from google.genai.errors import APIError
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import datetime

# ==================== KEEP-ALIVE SERVER CONFIGURATION ====================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Hafu is alive!")
    def log_message(self, format, *args):
        return 

def run_keep_alive_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Keep-alive online on port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


# ==================== BOT INITIALIZATION & KEY RING ====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Fetch your 4 different project keys from Render environment variables
# Format on Render dashboard config: Key1,Key2,Key3,Key4 (Strictly no spaces!)
RAW_KEYS = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in RAW_KEYS.split(",") if k.strip()]

# Fail-safe backup if you only supplied a traditional singular API key variable
if not GEMINI_KEYS and os.environ.get("GEMINI_API_KEY"):
    GEMINI_KEYS = [os.environ.get("GEMINI_API_KEY")]

CLIENT_RING = {}
CACHE_RING = {}
SELECTED_MODEL = 'gemini-3.5-flash'

# Global tracker pointing to which key is currently acting as primary
current_key_index = 0


# ==================== STRICT PERSONALITY SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving PSO2:NGS bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided database context to answer the user's question. 
- Look thoroughly through all the text, tables, and sections provided. If the text genuinely lacks a clear, identifiable answer, do NOT invent fake names or information. Instead, maintain character and say something like: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== INITIALIZE CACHES ON ALL 4 PROJECTS ====================
def setup_multi_project_caches():
    """
    Reads the 1.5MB file and uploads it securely to Google's context cache 
    across all available project keys. This avoids the 250K TPM limit completely.
    """
    if not os.path.exists("knowledge_database.txt"):
        print("⚠️ Warning: knowledge_database.txt not found. Running without cache configuration.")
        return

    if not GEMINI_KEYS:
        print("❌ CRITICAL: No Gemini API Keys found in GEMINI_KEY_RING or GEMINI_API_KEY!")
        return

    try:
        print("📂 Reading database file to construct API context cache...", flush=True)
        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            db_content = f.read()

        for i, key in enumerate(GEMINI_KEYS):
            print(f"☁️ Initializing project client [{i+1}/{len(GEMINI_KEYS)}]...", flush=True)
            client = genai.Client(api_key=key)
            CLIENT_RING[i] = client

            try:
                print(f"📦 Uploading cache asset to Project [{i+1}]...", flush=True)
                cache = client.caches.create(
                    model=SELECTED_MODEL,
                    config=types.CreateCachedContentConfig(
                        contents=[db_content],
                        ttl=datetime.timedelta(hours=24),
                        display_name=f"hafu_wiki_proj_{i}"
                    )
                )
                CACHE_RING[i] = cache.name
                print(f"✅ Cache active for Project [{i+1}] -> Reference ID: {cache.name}", flush=True)
            except Exception as ce:
                print(f"❌ Failed to cache on Project [{i+1}]: {ce}. This key will fallback to truncated text.")
                CACHE_RING[i] = None

    except Exception as e:
        print(f"❌ Critical error during multi-project cache build: {e}")


# ==================== DISCORD CORE EVENTS & COMMANDS ====================
@bot.event
async def on_ready():
    setup_multi_project_caches()
    print(f"🔥 Hafu is online and protected by a {len(GEMINI_KEYS)}-Project Key Ring!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING:
        await ctx.reply("Ah... *yawn* My brain keys aren't configured properly. Tell the admin~")
        return

    # Loop allows the request to attempt hitting every key in the pool before giving up
    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        cache_name = CACHE_RING.get(idx)
        
        try:
            # Optimal Scenario: Use the pre-cached server file (Cost: ~100 tokens total)
            if cache_name:
                response = client.models.generate_content(
                    model=SELECTED_MODEL,
                    contents=question,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.7,
                        max_output_tokens=300,
                        cached_content=cache_name
                    )
                )
            # Fallback Scenario: Safe-truncated input strings if cloud cache failed to compile
            else:
                with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                    db_content = f.read()[:40000]
                user_prompt = f"Database content:\n{db_content}\n\nQuestion: {question}"
                response = client.models.generate_content(
                    model=SELECTED_MODEL,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.7,
                        max_output_tokens=300
                    )
                )

            # Reply to user on discord and exit loop cleanly
            await ctx.reply(response.text.strip())
            return

        except APIError as api_err:
            # If the current project key has hit its 5 RPM free allocation cap
            if api_err.code == 429:
                print(f"⚠️ Project Key Ring index [{idx+1}] hit rate limits. Shifting to next key pointer...")
                # Instantly move index pointer forward to next project bucket
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue # Immediately triggers next iteration with the updated key
            else:
                print(f"❌ API Error on Ring Key [{idx+1}]: {api_err}")
                await ctx.reply("*yawn* My head hurts... Something went wrong inside the database query.")
                return
        except Exception as e:
            print(f"❌ Unexpected System Crash on Key [{idx+1}]: {e}")
            await ctx.reply("Sorry~ Hafu got distracted by a butterfly. Try asking again!")
            return

    # Triggers only if all 4 projects threw a concurrent 429 back-to-back
    await ctx.reply("Ugh... *yawns loudly* The whole lobby is screaming at me at once! Give me a minute to rest, okay?~")


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN environment variable is missing!")

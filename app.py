import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types
from google.genai.errors import APIError
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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
RAW_KEYS = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in RAW_KEYS.split(",") if k.strip()]

if not GEMINI_KEYS and os.environ.get("GEMINI_API_KEY"):
    GEMINI_KEYS = [os.environ.get("GEMINI_API_KEY")]

CLIENT_RING = {}
CACHE_RING = {}
SELECTED_MODEL = 'gemini-3.5-flash'
current_key_index = 0


# ==================== THE STRICT PERSONALITY SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving Phantasy Star Online 2: New Genesis (PSO2:NGS) bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided database context to answer the user's question. 
- Look thoroughly through all the text, tables, and sections provided. If the text genuinely lacks a clear, identifiable answer, do NOT invent fake names or information. Instead, maintain character and say something like: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== INITIALIZE CLOUD CACHES (FULL FILE) ====================
def setup_multi_project_caches():
    """
    Reads the entire 1.5MB file and deploys it safely to Google's cloud memory cache.
    Uses the correct string configuration for the TTL argument to pass validation.
    """
    if not os.path.exists("knowledge_database.txt"):
        print("⚠️ Warning: knowledge_database.txt not found.", flush=True)
        return

    try:
        print("📂 Reading entire 1.5MB database into memory...", flush=True)
        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            full_db_content = f.read()

        for i, key in enumerate(GEMINI_KEYS):
            print(f"☁️ Connecting to Google Cloud Project [{i+1}/{len(GEMINI_KEYS)}]...", flush=True)
            client = genai.Client(api_key=key)
            CLIENT_RING[i] = client

            try:
                print(f"📦 Compiling and caching complete file on Project [{i+1}]...", flush=True)
                # FIX: ttl MUST be passed as a string duration (e.g. "86400s" for 24 hours)
                cache = client.caches.create(
                    model=SELECTED_MODEL,
                    config=types.CreateCachedContentConfig(
                        contents=[full_db_content],
                        system_instruction=SYSTEM_PROMPT,
                        ttl="86400s",
                        display_name=f"hafu_complete_data_{i}"
                    )
                )
                CACHE_RING[i] = cache.name
                print(f"✅ Cache fully deployed on Project [{i+1}] -> Reference ID: {cache.name}", flush=True)
            except Exception as ce:
                print(f"❌ Failed to build cloud cache on Project [{i+1}]: {ce}", flush=True)
                CACHE_RING[i] = None

    except Exception as e:
        print(f"❌ Critical error during macro database read: {e}", flush=True)


# ==================== DISCORD CORE COMMANDS ====================
@bot.event
async def on_ready():
    setup_multi_project_caches()
    print(f"🔥 Hafu is online!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING:
        await ctx.reply("Ah... *yawn* My brain keys aren't configured properly. Tell the admin~")
        return

    # Pack the incoming question into a formal user content container
    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=question)]
    )

    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        cache_name = CACHE_RING.get(idx)
        
        try:
            if cache_name:
                response = client.models.generate_content(
                    model=SELECTED_MODEL,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        temperature=0.4,
                        max_output_tokens=1000,
                        cached_content=cache_name
                    )
                )
                
                try:
                    finish_reason = response.candidates[0].finish_reason
                    print(f"🔍 [Key {idx+1}] Finish Reason: {finish_reason} | Prompt Tokens: {response.usage_metadata.prompt_token_count} | Output Tokens: {response.usage_metadata.candidates_token_count}", flush=True)
                except Exception:
                    pass

                text_out = response.text.strip()
                if not text_out:
                    text_out = "*yawns* I found something but I'm too sleepy to format it cleanly..."
                
                await ctx.reply(text_out)
                return
                
            else:
                print(f"⚠️ Warning: Running fallback raw evaluation on Key Ring index [{idx+1}]", flush=True)
                with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                    fallback_text = f.read()[:40000]
                user_prompt = f"Database:\n{fallback_text}\n\nQuestion: {question}"
                response = client.models.generate_content(
                    model=SELECTED_MODEL,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.5,
                        max_output_tokens=800
                    )
                )
                await ctx.reply(response.text.strip())
                return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Project [{idx+1}] rate limited. Automatically shifting to next key project...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue 
            else:
                print(f"❌ API Error on Project [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("*yawn* My head hurts... Something went wrong inside the database query.")
                return
        except Exception as e:
            print(f"❌ Unexpected Error on Project [{idx+1}]: {e}", flush=True)
            await ctx.reply("Sorry~ Hafu got distracted by a butterfly. Try asking again!")
            return

    await ctx.reply("Ugh... *yawns loudly* The whole lobby is screaming at me at once! Give me a minute to rest, okay?~")


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN environment variable is missing!")

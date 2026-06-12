import os
import glob
import re
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

RAW_KEYS = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in RAW_KEYS.split(",") if k.strip()]

if not GEMINI_KEYS and os.environ.get("GEMINI_API_KEY"):
    GEMINI_KEYS = [os.environ.get("GEMINI_API_KEY")]

CLIENT_RING = {}
SELECTED_MODEL = 'gemini-2.5-flash'
current_key_index = 0

LOCAL_FILE_MAP = {}

# ==================== ZERO-TOKEN INTELLIGENT ROUTER MAP ====================
ROUTING_KEYWORDS = {
    "sword": "sword",
    "wired lance": "wired_lance", "wiredlance": "wired_lance",
    "partisan": "partisan",
    "twin dagger": "twin_daggers", "twindagger": "twin_daggers", "dagger": "twin_daggers",
    "dual blade": "dual_blades", "dualblade": "dual_blades",
    "knuckle": "knuckles",
    "默默": "katana", "katana": "katana",
    "assault rifle": "assault_rifle", "rifle": "assault_rifle",
    "twin machine gun": "twin_machine_guns", "tmg": "twin_machine_guns", "machine gun": "twin_machine_guns",
    "talis": "talis",
    "wand": "wand",
    "harmonizer": "harmonizer", "takt": "harmonizer",
    "jet boot": "jet_boots", "jetboot": "jet_boots",
    
    "hunter": "hunter", "hu": "hunter",
    "fighter": "fighter", "fi": "fighter",
    "ranger": "ranger", "ra": "ranger",
    "gunner": "gunner", "gu": "gunner",
    "force": "force", "fo": "force",
    "techter": "techter", "te": "techter",
    "braver": "braver", "br": "braver",
    "bouncer": "bouncer", "bo": "bouncer",
    "waker": "waker", "wa": "waker",
    "slayer": "slayer", "sl": "slayer",
    
    "class": "general_classes", "ex style": "general_classes",
    "weapon": "general_weapons",
    "armor": "armor", "unit": "armor",
    "ring": "skill_rings",
    "enhance": "enhancement", "limit break": "enhancement",
    
    # Technique mappings protected against short class collisions
    "technique": "techniques", "tech": "techniques", 
    "light": "techniques", "fire": "techniques", "ice": "techniques", 
    "lightning": "techniques", "wind": "techniques", "dark": "techniques",
    
    "augment": "augments", "affix": "augments", "op": "augments",
    "task": "tasks", "quest": "urgent_quests", "urgent": "urgent_quests",
    "region": "regions", "area": "regions", "map": "regions",
    "history": "arks_history", "lore": "arks_history",
    
    # Event keywords now explicitly mapping to live announcements
    "event": "sega_live_feed", "events": "sega_live_feed",
    "update": "sega_live_feed", "announcement": "sega_live_feed", "news": "sega_live_feed"
}

def index_local_databases():
    global LOCAL_FILE_MAP
    LOCAL_FILE_MAP.clear()
    base_dir = "knowledge_base"
    
    if not os.path.exists(base_dir):
        print(f"⚠️ Warning: Target storage root '{base_dir}' not found on disk.", flush=True)
        return

    text_files = glob.glob(os.path.join(base_dir, "**", "*.txt"), recursive=True)
    for file_path in text_files:
        stem = os.path.splitext(os.path.basename(file_path))[0]
        LOCAL_FILE_MAP[stem] = file_path
        
    print(f"📂 Indexed {len(LOCAL_FILE_MAP)} local micro-databases successfully.", flush=True)


def route_user_query(question_text):
    """
    Evaluates user input using regular expression word boundaries 
    to eliminate partial matching substring collisions.
    """
    query = question_text.lower()
    
    for keyword, stem in ROUTING_KEYWORDS.items():
        # strict boundary checks prevent 'te' from triggering on 'techniques'
        if re.search(r'\b' + re.escape(keyword) + r'\b', query):
            if stem in LOCAL_FILE_MAP:
                print(f"🎯 Route matched: '{keyword}' ──► Local File: [{LOCAL_FILE_MAP[stem]}]", flush=True)
                return LOCAL_FILE_MAP[stem]

    # Explicit logged fallback handling
    fallback_stem = None
    if "frontpage" in LOCAL_FILE_MAP:
        fallback_stem = "frontpage"
    elif "general_weapons" in LOCAL_FILE_MAP:
        fallback_stem = "general_weapons"
    elif LOCAL_FILE_MAP:
        fallback_stem = list(LOCAL_FILE_MAP.keys())[0]

    if fallback_stem:
        print(f"⚠️ No exact keyword route. Fallback triggered ──► Local File: [{LOCAL_FILE_MAP[fallback_stem]}]", flush=True)
        return LOCAL_FILE_MAP[fallback_stem]
        
    return None


# ==================== SYSTEM CHARACTER PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving Phantasy Star Online 2: New Genesis (PSO2:NGS) bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided Context Database contents to answer the user's question.
- Keep your responses direct, concise, and aligned with game specifics. Do not guess stats or build names.
- If the context does not contain the answer, say so in character: "*yawns* I don't see anything like that in my notes... Maybe go check the blocks yourself or ask a pro in the lobby."
"""


# ==================== DISCORD CORE COMMANDS ====================
@bot.event
async def on_ready():
    for i, key in enumerate(GEMINI_KEYS):
        CLIENT_RING[i] = genai.Client(api_key=key)
    
    index_local_databases()
    print(f"🔥 Hafu is online and fully responsive with {len(GEMINI_KEYS)} keys!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING or not LOCAL_FILE_MAP:
        await ctx.reply("Ah... *yawn* My local context files are missing. Did the automation sync run yet~?")
        return

    target_file_path = route_user_query(question)
    if not target_file_path:
        await ctx.reply("*yawn* I don't even know where to look for that info...")
        return

    try:
        with open(target_file_path, "r", encoding="utf-8") as f:
            context_data = f.read()
    except Exception as e:
        print(f"❌ Local read failed for {target_file_path}: {e}", flush=True)
        await ctx.reply("Ugh, my notebooks are torn. Couldn't read the files.")
        return

    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)

        try:
            response = await client.aio.models.generate_content(
                model=SELECTED_MODEL,
                contents=[
                    f"CONTEXT DATABASE:\n{context_data}",
                    f"User Question: {question}"
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.5,
                    max_output_tokens=600
                )
            )
            
            try:
                print(f"🔍 [Key {idx+1}] Request Handled | Reason: {response.candidates[0].finish_reason}", flush=True)
            except Exception:
                pass

            text_out = response.text.strip()
            if not text_out:
                text_out = "*yawns* I checked the file, but my head is too empty to give a good answer right now..."
            
            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Key [{idx+1}] hit rate limits. Swapping positions...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue 
            else:
                print(f"❌ API Error on Key [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("*yawn* Something went wrong inside the API pipeline.")
                return
        except Exception as e:
            print(f"❌ Unexpected Error on Key [{idx+1}]: {e}", flush=True)
            await ctx.reply("Ugh, Hafu got disconnected for a second. Try again?")
            return

    await ctx.reply("Ah... *yawns loudly* Too many requests at once. My brain is on cooldown~")


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN is completely missing from environment variables!")

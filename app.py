import os
import glob
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
SELECTED_MODEL = 'gemini-3.5-flash'
current_key_index = 0

# Master tracking storage for uploaded Google File API handles
# Structure: GOOGLE_FILE_MAP[key_index][file_stem_name] = google_file_object
GOOGLE_FILE_MAP = {}

# ==================== ZERO-TOKEN INTELLIGENT ROUTER MAP ====================
# Maps common in-game search phrases and abbreviations directly to your granular database stems
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
    "technique": "techniques", "tech": "techniques",
    "augment": "augments", "affix": "augments", "op": "augments",
    
    "task": "tasks", "quest": "urgent_quests", "urgent": "urgent_quests",
    "region": "regions", "area": "regions", "map": "regions",
    "history": "arks_history", "lore": "arks_history",
    
    "update": "sega_live_feed", "announcement": "sega_live_feed", "news": "sega_live_feed"
}


def mount_sub_databases():
    """
    Scans the local knowledge_base directories and registers every micro-database
    to Google's File API for every single key configuration inside the client ring.
    """
    global GOOGLE_FILE_MAP
    base_dir = "knowledge_base"
    
    if not os.path.exists(base_dir):
        print(f"⚠️ Error: Target storage root '{base_dir}' does not exist! Run compilation first.", flush=True)
        return

    # Find all text data files inside subdirectories recursively
    text_files = glob.glob(os.path.join(base_dir, "**", "*.txt"), recursive=True)
    if not text_files:
        print("⚠️ Warning: No sub-database configuration files (.txt) found to mount!", flush=True)
        return

    print(f"📂 Found {len(text_files)} standalone micro-databases. Syncing with Google File API...", flush=True)

    # Mount files separately across every project client to prevent cross-key 404 validation failures
    for idx, client in CLIENT_RING.items():
        GOOGLE_FILE_MAP[idx] = {}
        print(f" 🔗 Mounting remote filesystem entities for Key Ring Node [{idx+1}]...", flush=True)
        
        for file_path in text_files:
            # Extract file stem name (e.g., 'knowledge_base/weapons/sword.txt' -> 'sword')
            stem = os.path.splitext(os.path.basename(file_path))[0]
            try:
                uploaded_ref = client.files.upload(file=file_path)
                GOOGLE_FILE_MAP[idx][stem] = uploaded_ref
            except Exception as e:
                print(f"   ❌ Failed to sync file asset [{stem}] for Key [{idx+1}]: {e}", flush=True)

    print("✅ All sub-category cloud database nodes successfully mounted and active!", flush=True)


def route_user_query(question_text, current_idx):
    """
    Inspects user input locally using string evaluation to retrieve 
    the exact matching sub-database Google file object reference.
    """
    query = question_text.lower()
    client_files = GOOGLE_FILE_MAP.get(current_idx, {})
    
    # Run structural keyword matching checks
    for keyword, stem in ROUTING_KEYWORDS.items():
        if keyword in query:
            if stem in client_files:
                print(f"🎯 Route matched: '{keyword}' ──► Mount Node File: [{stem}.txt]", flush=True)
                return client_files[stem]

    # Clean fallbacks if no precise keyword triggers match
    if "general_weapons" in client_files:
        return client_files["general_weapons"]
    elif "frontpage" in client_files:
        return client_files["frontpage"]
        
    # Absolute bare fallback (returns first element available)
    return list(client_files.values())[0] if client_files else None


# ==================== SYSTEM CHARACTER PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving Phantasy Star Online 2: New Genesis (PSO2:NGS) bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the attached database file reference attachment to answer the user's question.
- Keep your responses direct, concise, and aligned with game specifics. Do not guess stats or build names.
- If the attached context does not contain the answer, say so in character: "*yawns* I don't see anything like that in my notes... Maybe go check the blocks yourself or ask a pro in the lobby."
"""


# ==================== DISCORD CORE COMMANDS ====================
@bot.event
async def on_ready():
    # 1. Initialize Client Instances
    for i, key in enumerate(GEMINI_KEYS):
        CLIENT_RING[i] = genai.Client(api_key=key)
    
    # 2. Run Remote File System Mount
    mount_sub_databases()
    print(f"🔥 Hafu is online and fully configured with {len(GEMINI_KEYS)} keys!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING or not GOOGLE_FILE_MAP:
        await ctx.reply("Ah... *yawn* My cloud filesystem maps are completely missing. Tell the admin~")
        return

    # Request loop over key ring to cleanly bypass 429 errors or rate blocks
    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        
        # Determine the targeted micro-database reference for this active client node
        target_file_node = route_user_query(question, idx)
        
        if not target_file_node:
            current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
            continue

        try:
            # Call the model natively attaching the single target cloud database text reference object
            response = client.models.generate_content(
                model=SELECTED_MODEL,
                contents=[target_file_node, f"User Question: {question}"],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=600
                )
            )
            
            # Simple log verification tracker
            try:
                print(f"🔍 [Key {idx+1}] File Processed Natively | Finish Reason: {response.candidates[0].finish_reason}", flush=True)
            except Exception:
                pass

            text_out = response.text.strip()
            if not text_out:
                text_out = "*yawns* I checked the file, but my head is too empty to give a good answer right now..."
            
            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Key [{idx+1}] hit rate limits. Swapping pool position...", flush=True)
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

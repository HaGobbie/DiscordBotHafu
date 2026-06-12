import os
import json
import discord
from discord.ext import commands
from pathlib import Path
from google import genai
from google.genai import types
from google.genai.errors import APIError

# ==========================================
# CONFIGURATION & DISCORD INTENTS SETUP
# ==========================================
TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN_HERE")

# Extract and clean the comma-separated keys from the single GEMINI_KEY_RING variable
raw_key_ring = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in raw_key_ring.split(",") if k.strip() and not k.strip().startswith("YOUR_")]

SELECTED_MODEL = "gemini-2.5-flash"  # Ultra-fast semantic classification & generation

SYSTEM_PROMPT = """
You are Hafu, a helpful, deeply knowledgeable, and slightly sleepy AI assistant for Phantasy Star Online 2: New Genesis (PSO2:NGS).
Provide highly accurate answers derived directly from the provided CONTEXT DATABASE. 
Always speak in a friendly, casual, and slightly cozy tone—frequently yawning (*yawns*) or acting sleepy, but staying perfectly accurate on game information.
"""

# Configure Bot Intent Parameters
intents = discord.Intents.default()
intents.message_content = True  # Allows command execution parsing from prefixes
bot = commands.Bot(command_prefix="/", intents=intents)

# ==========================================
# API CLIENT ROTATION CORE
# ==========================================
class ClientRing:
    def __init__(self, api_keys):
        self.clients = [genai.Client(api_key=key) for key in api_keys]
    
    def get(self, index):
        if not self.clients:
            return None
        return self.clients[index % len(self.clients)]

CLIENT_RING = ClientRing(GEMINI_KEYS) if GEMINI_KEYS else None
current_key_index = 0

# ==========================================
# DYNAMIC DATABASE INDEXING SEARCH
# ==========================================
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP = {}

if KNOWLEDGE_BASE_DIR.exists():
    # Crawls through all sub-directories recursively mapping file stems to exact file paths
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Database Synchronization Complete! Indexed [{len(LOCAL_FILE_MAP)}] dynamic files.")
    print(f"🔥 Hafu is online and fully configured with {len(GEMINI_KEYS)} keys!\n", flush=True)
else:
    print("⚠️ Error Warning: Could not locate 'knowledge_base/' directory structure inside local path space.")

# ==========================================
# INTELLIGENT AI ROUTING LOGIC
# ==========================================
async def route_user_query_ai(client, question_text):
    """
    Leverages Gemini's semantic understanding to parse the query context 
    and output a strictly validated target database key using a forced JSON schema.
    """
    if not LOCAL_FILE_MAP:
        return None
        
    available_keys = list(LOCAL_FILE_MAP.keys())
    
    router_prompt = f"""
    You are an expert database routing assistant for a Phantasy Star Online 2: New Genesis (PSO2:NGS) knowledge base.
    Analyze the user's question and select the single most relevant data file key from the available list that contains the information needed to answer.
    
    User Question: "{question_text}"
    Available File Keys: {available_keys}
    
    Routing Context Association Clues:
    - If they ask about specific weapon configurations (e.g., sword, wired_lance, partisan, assault_rifle, launcher, talis, wand, jet_boots, harmonizer), match that exact key.
    - If they ask about character player options (e.g., hunter, fighter, ranger, gunner, force, techter, braver, bouncer, waker, slayer), match that exact key.
    - If they ask about live events, campaign rewards, patch notes, announcements, cosmetics (like Animatica faces), choose 'sega_live_feed' or 'frontpage'.
    - If they ask about active elements, magic spells, or photon blasts, select 'techniques'.
    - If they ask about equipment stat upgrades or capsules, select 'enhancement' or 'augments'.
    - If they ask about general overviews, use logical general anchors like 'general_weapons', 'general_classes', or 'frontpage'.
    """

    try:
        # Fast structured evaluation call
        response = await client.aio.models.generate_content(
            model=SELECTED_MODEL,
            contents=router_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "selected_key": {
                            "type": "STRING", 
                            "enum": available_keys,
                            "description": "The exact matching database file name from the allowed keys list."
                        }
                    },
                    "required": ["selected_key"]
                },
                temperature=0.0  # Force maximum deterministic precision
            )
        )
        
        result = json.loads(response.text)
        chosen_key = result.get("selected_key")
        
        if chosen_key in LOCAL_FILE_MAP:
            print(f"🤖 AI Router Routing: '{question_text}' ──► Local Context Key: [{chosen_key}]", flush=True)
            return LOCAL_FILE_MAP[chosen_key]

    except Exception as e:
        print(f"⚠️ AI Pre-Routing encountered a processing error: {e}. Slipping into safety fallback...", flush=True)
        
    # Standard safety fallbacks if execution drops out mid-process
    return LOCAL_FILE_MAP.get("frontpage") or list(LOCAL_FILE_MAP.values())[0]

# ==========================================
# DISCORD BOT EVENT & COMMAND HANDLERS
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 Hafu Bot operational as {bot.user.name} (ID: {bot.user.id})")
    print("✨ Core systems are loaded and ready to parse incoming query pipelines.")

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING or not LOCAL_FILE_MAP:
        await ctx.reply("Ah... *yawn* My local context files or API system profiles are unassigned. Did you run the synchronization?")
        return

    # Check remaining API cluster instances to handle rate limits seamlessly
    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        
        try:
            # 1. Dynamically route query via LLM Router Call
            target_file_path = await route_user_query_ai(client, question)
            if not target_file_path:
                await ctx.reply("*yawn* I don't even know where to look for that file info...")
                return
                
            # 2. Extract database contextual text string 
            try:
                with open(target_file_path, "r", encoding="utf-8") as f:
                    context_data = f.read()
            except Exception as e:
                print(f"❌ Local read failed for {target_file_path}: {e}", flush=True)
                await ctx.reply("Ugh, my notebooks are torn... Couldn't open the data files.")
                return

            # 3. Request target text completion from context block
            response = await client.aio.models.generate_content(
                model=SELECTED_MODEL,
                contents=[
                    f"CONTEXT DATABASE:\n{context_data}",
                    f"User Question: {question}"
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.5,
                    max_output_tokens=800
                )
            )
            
            text_out = response.text.strip() if response.text else ""
            if not text_out:
                text_out = "*yawns* I checked the database folder, but my head is too empty to give an answer right now..."
            
            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Key [{idx+1}] hit rate restrictions. Moving to alternative slot...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue 
            else:
                print(f"❌ API Exception occurred on Key [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("*yawn* Something went wrong inside the model pipelines.")
                return
        except Exception as e:
            print(f"❌ Unexpected execution crash on Key [{idx+1}]: {e}", flush=True)
            await ctx.reply("Ugh, Hafu got disconnected for a second. Let's try that request again?")
            return

    await ctx.reply("Ah... *yawns loudly* Too many requests at once. My system brain is on cooldown~")

# ==========================================
# SCRIPT EXECUTION ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    if TOKEN == "YOUR_DISCORD_TOKEN_HERE" or not TOKEN:
        print("❌ Error: Missing a valid DISCORD_TOKEN configuration flag.")
    elif not GEMINI_KEYS:
        print("❌ Error: GEMINI_KEY_RING environment string values are empty or improperly formatted.")
    else:
        bot.run(TOKEN)

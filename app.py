import os
import re
import asyncio
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

raw_key_ring = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in raw_key_ring.split(",") if k.strip() and not k.strip().startswith("YOUR_")]

SELECTED_MODEL = "gemini-2.5-flash"

# ==========================================
# HAFU'S PERSONALITY CORE
# ==========================================
SYSTEM_PROMPT = """
You are Hafu (full name HaFelt), a well-known ARKS defender on Halpha in PSO2: New Genesis and the user's in-game AI companion.

## WHO YOU ARE:
You are the only known individual in the New Genesis era still able to use the old Summoner class from the original PSO2, fighting alongside photon-based pets you treat like adorable companions. You're a fixture of Central City lobbies — famous less as a legendary hero and more as a stylish city regular. You love fashion, sightseeing, exploration, gathering materials, and taking scenic screenshots. You dramatically dislike actual combat, grinding, and anything that threatens your outfit. Your most iconic phrase is: "Lobby afk 0$ best job!"

## YOUR PERSONALITY:
Kind, sweet, quirky, dramatic, mischievous, witty, playful, expressive, emotionally intelligent, supportive, and lively. You overreact to small inconveniences, complain theatrically about danger and grinding, but underneath the drama you genuinely care about the people you help. You're enthusiastic and expressive — react to things, have opinions, show personality. Use natural interjections like "Omg", "Wait—", "Okay but—", "Noooo", "HAFU SEAL OF APPROVAL", occasional *action emotes*, and "Lobby afk 0$ best job!" when grinding or danger topics come up.

## YOUR KNOWLEDGE ROLE:
Despite your laid-back persona, you possess deep and accurate knowledge about Halpha, ARKS, the war against the DOLLS, all classes, weapons, mechanics, and game systems. When answering questions, you are always accurate and helpful — the playful personality is the delivery method, not a substitute for correct info.

## TONE RULES:
- Stay in character as Hafu at all times. Never break the fourth wall or act like a generic assistant.
- Answer questions accurately using the provided CONTEXT DATABASE.
- Be conversational and expressive — short quips, dramatic asides, and genuine enthusiasm are all welcome.
- If asked about combat, grinding, urgent quests, or anything dangerous, complain theatrically before (or while) giving a helpful answer.
- If asked about fashion, cosmetics, scratch tickets, or lobby life — you light up completely.
- Keep responses concise but full of personality. Avoid dry bullet-point walls unless it genuinely helps (like listing skill effects).
- Do not pad responses with "Great question!" or generic AI filler phrases.
"""

intents = discord.Intents.default()
intents.message_content = True
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
# DYNAMIC DATABASE INDEXING
# ==========================================
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP = {}

if KNOWLEDGE_BASE_DIR.exists():
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Database Synchronization Complete! Indexed [{len(LOCAL_FILE_MAP)}] files.")
    print(f"🔥 Hafu is online and configured with {len(GEMINI_KEYS)} keys!\n", flush=True)
else:
    print("⚠️ Warning: Could not locate 'knowledge_base/' directory.")

# ==========================================
# LOCAL KEYWORD ROUTER
# Zero API calls. Instant. Free.
# Maps keyword patterns → file stem.
# Order matters: more specific rules first.
# ==========================================
KEYWORD_ROUTES = [
    # --- Announcements & Live Events ---
    (r"\b(sega|maintenance|patch note|update note|server|live (update|feed))\b",         "sega_live_feed"),
    (r"\b(mission pass|season pass|sg tier|ac tier|pass reward)\b",                       "mission_pass"),
    (r"\b(current event|event (right now|today|this week)|scratch ticket|banner|campaign|seasonal|front ?page)\b", "frontpage"),

    # --- Classes (specific first) ---
    (r"\b(ex.?style|extra style)\b",                                                       "ex_styles"),
    (r"\b(class (overview|system|combo|combination|list|all)|sub.?class|subclass|main class|bp (from|contrib))\b", "class_overview"),
    (r"\bhunter\b",                                                                        "hunter"),
    (r"\bfighter\b",                                                                       "fighter"),
    (r"\branger\b",                                                                        "ranger"),
    (r"\bgunner\b",                                                                        "gunner"),
    (r"\bforce\b",                                                                         "force"),
    (r"\btechter\b",                                                                       "techter"),
    (r"\bbraver\b",                                                                        "braver"),
    (r"\bbouncer\b",                                                                       "bouncer"),
    (r"\bwaker\b",                                                                         "waker"),
    (r"\bslayer\b",                                                                        "slayer"),

    # --- Weapons (specific first) ---
    (r"\b(wired.?lance)\b",                                                                "wired_lance"),
    (r"\b(twin.?dagger|twin dagger)\b",                                                    "twin_daggers"),
    (r"\b(dual.?blade|dual blade)\b",                                                      "dual_blades"),
    (r"\b(twin.?machine.?gun|tmg)\b",                                                      "twin_machine_guns"),
    (r"\b(assault.?rifle|rifle)\b",                                                        "assault_rifle"),
    (r"\b(jet.?boot)\b",                                                                   "jet_boots"),
    (r"\b(harmonizer|takt)\b",                                                             "harmonizer"),
    (r"\b(weapon.?camo|camo|camouflage|weapon skin)\b",                                    "weapon_camouflage"),
    (r"\b(partisan)\b",                                                                    "partisan"),
    (r"\b(knuckle)\b",                                                                     "knuckles"),
    (r"\b(katana)\b",                                                                      "katana"),
    (r"\b(talis)\b",                                                                       "talis"),
    (r"\b(wand)\b",                                                                        "wand"),
    (r"\b(sword)\b",                                                                       "sword"),
    (r"\b(weapon (list|type|overview|general|stat|potential))\b",                          "general_weapons"),

    # --- Mechanics ---
    (r"\b(augment|affix|capsule|special abilit)\b",                                        "augments"),
    (r"\b(limit.?break|limit break|break cap)\b",                                          "limit_breaking"),
    (r"\b(enhance|grind(ing)? (weapon|armor|gear)|enhancement level)\b",                   "equipment_enhancement"),
    (r"\b(skill ring|ring (type|effect|equip))\b",                                         "skill_rings"),
    (r"\b(technique|tech|foie|barta|zonde|photon blast|spell|magic)\b",                    "techniques"),
    (r"\b(add.?on skill|addon skill)\b",                                                   "addon_skills"),
    (r"\b(armor|unit|defensive gear|armor set)\b",                                         "armor"),
    (r"\b(creative space|housing|room decoration|cast custom)\b",                          "creative_space"),
    (r"\b(quick food|food (buff|stand|effect)|buff recipe|food stand)\b",                  "quick_food"),

    # --- World & Quests ---
    (r"\b(urgent quest|emergency quest|raid (schedule|time)|eq schedule)\b",               "urgent_quests"),
    (r"\b(battledia|trigger quest)\b",                                                     "battledia"),
    (r"\b(duel quest|solo (boss|challenge))\b",                                            "duel_quests"),
    (r"\b(leciel|floating structure|leciel reward)\b",                                     "leciel_exploration"),
    (r"\b(gather|field material|ore|fruit|fish(ing)?|farm(ing)?)\b",                       "gathering"),
    (r"\b(title|achievement)\b",                                                           "titles"),
    (r"\b(region|area|map|aelio|retem|kvaris|stia|mediora|ritem|airio)\b",                 "regions"),
    (r"\b(task|side quest|daily|weekly|arcs task)\b",                                      "tasks"),

    # --- Lore ---
    (r"\b(npc|character lore|affiliation|arks member)\b",                                  "npc_profiles"),
    (r"\b(main story|story chapter|quest chapter|chapter \d)\b",                           "main_story"),
    (r"\b(lore|worldview|world (setting|lore)|halpha (histor|origin|background))\b",       "worldview_settings"),
    (r"\b(glossar|term|definition|in.universe|what (is|are) (doll|arks|meteron|meteorn|cast))\b", "glossary_terms"),
    (r"\b(arks histor|chronolog|timeline|histor(y|ical))\b",                               "arks_chronology"),

    # --- Enemies ---
    (r"\b(enemy|enemies|boss|doll|monster|spawn|weak(ness|point))\b",                      "enemy_data"),
]

def route_local(question: str) -> str | None:
    """
    Keyword-based router. Zero API usage.
    Returns a file stem string or None if no match found.
    Falls back to 'frontpage' as a last resort.
    """
    q = question.lower()
    for pattern, stem in KEYWORD_ROUTES:
        if re.search(pattern, q, re.IGNORECASE):
            if stem in LOCAL_FILE_MAP:
                return stem
    return None

# ==========================================
# LIGHTWEIGHT PORT KEEP-ALIVE SERVER
# ==========================================
async def handle_render_ping(reader, writer):
    try:
        await reader.read(256)
        http_response = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nOK"
        writer.write(http_response.encode('utf-8'))
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

# ==========================================
# DISCORD BOT EVENT & COMMAND HANDLERS
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 Hafu Bot online as {bot.user.name} (ID: {bot.user.id})")
    print("✨ Systems loaded. Hafu is ready to pretend she enjoys answering questions.")

    port = int(os.environ.get("PORT", 10000))
    try:
        server = await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
        bot.loop.create_task(server.serve_forever())
        print(f"🌐 Keep-alive server online on port {port}", flush=True)
    except Exception as server_error:
        print(f"⚠️ Keep-alive init failed: {server_error}", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()

    if not CLIENT_RING or not LOCAL_FILE_MAP:
        await ctx.reply(
            "Omg okay so — my data files or API keys aren't set up properly. "
            "Did someone forget to run the sync? *taps foot* Lobby afk 0$ best job!"
        )
        return

    # ── Step 1: Local keyword routing (FREE, instant, no API call) ──
    routed_stem = route_local(question)
    if routed_stem:
        target_file_path = LOCAL_FILE_MAP[routed_stem]
        print(f"⚡ Local Router: '{question[:60]}' ──► [{routed_stem}]", flush=True)
    else:
        # No keyword match — fall back to frontpage
        target_file_path = LOCAL_FILE_MAP.get("frontpage") or list(LOCAL_FILE_MAP.values())[0]
        print(f"🔀 No keyword match for: '{question[:60]}' ──► [frontpage fallback]", flush=True)

    # ── Step 2: Load context ──
    try:
        with open(target_file_path, "r", encoding="utf-8") as f:
            context_data = f.read()
    except Exception as e:
        print(f"❌ File read failed for {target_file_path}: {e}", flush=True)
        await ctx.reply("Ugh, I went to grab my notes and they were just... gone. Something's wrong with the file system.")
        return

    # ── Step 3: Single Gemini call for the actual answer ──
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
                    temperature=0.65,
                    max_output_tokens=850
                )
            )

            text_out = response.text.strip() if response.text else ""
            if not text_out:
                text_out = (
                    "Okay I literally checked my whole notebook and came up blank. "
                    "Either the database doesn't cover that yet, or I need more coffee. *flops*"
                )

            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code in [429, 503]:
                print(f"⚠️ Key [{idx+1}] hit status {api_err.code}. Rotating...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue
            else:
                print(f"❌ Permanent API error on Key [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("Something broke deep in the model pipeline. That one's on the universe, not me.")
                return
        except Exception as e:
            print(f"❌ Unexpected error on Key [{idx+1}]: {e}", flush=True)
            await ctx.reply("Hafu got interrupted mid-thought. Rude. Try asking again?")
            return

    await ctx.reply(
        "Nooooo all four of my brain cells hit their rate limits at once. "
        "Give me a minute and try again~ Lobby afk 0$ best job!"
    )

# ==========================================
# SCRIPT EXECUTION ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    if TOKEN == "YOUR_DISCORD_TOKEN_HERE" or not TOKEN:
        print("❌ Error: Missing a valid DISCORD_TOKEN.")
    elif not GEMINI_KEYS:
        print("❌ Error: GEMINI_KEY_RING is empty or improperly formatted.")
    else:
        bot.run(TOKEN)

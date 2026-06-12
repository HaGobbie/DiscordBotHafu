import os
import json
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

# Extract and clean the comma-separated keys from the single GEMINI_KEY_RING variable
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

# Configure Bot Intent Parameters
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
# ROUTING HINT MAP (stem → category description)
# Keeps the AI router grounded on what each file actually contains
# ==========================================
ROUTING_HINTS = {
    # Announcements
    "frontpage":             "General NGS front page news, current events, patch notes, campaigns, scratch ticket banners, seasonal content",
    "mission_pass":          "Mission Pass season tracks, rewards, SG and AC tiers",
    "sega_live_feed":        "Official SEGA live update stream, latest patch announcements, maintenance notices",

    # Classes
    "class_overview":        "General overview of all classes, sub-class mechanics, class combinations, BP contributions",
    "ex_styles":             "EX Style system, how EX styles work, unlocking EX styles",
    "hunter":                "Hunter class skills, skill tree, Photon Arts, playstyle — Sword, Wired Lance, Partisan",
    "fighter":               "Fighter class skills, skill tree, Photon Arts, playstyle — Twin Daggers, Dual Blades, Knuckles",
    "ranger":                "Ranger class skills, skill tree, Photon Arts, playstyle — Assault Rifle, Launcher",
    "gunner":                "Gunner class skills, skill tree, Photon Arts, playstyle — Twin Machine Guns",
    "force":                 "Force class skills, skill tree, Techniques, playstyle — Rod, Talis",
    "techter":               "Techter class skills, skill tree, support Techniques, playstyle — Wand, Talis",
    "braver":                "Braver class skills, skill tree, Photon Arts, playstyle — Katana, Assault Rifle",
    "bouncer":               "Bouncer class skills, skill tree, Photon Arts, playstyle — Jet Boots, Dual Blades",
    "waker":                 "Waker class skills, skill tree, Photon Arts, playstyle — Harmonizer/Takt, pets",
    "slayer":                "Slayer class skills, skill tree, Photon Arts, playstyle — Gunblade",

    # Weapons
    "general_weapons":       "General weapon systems, weapon categories, potentials, weapon stats overview",
    "sword":                 "Sword weapon stats, Photon Arts list, notable swords",
    "wired_lance":           "Wired Lance weapon stats, Photon Arts list",
    "partisan":              "Partisan weapon stats, Photon Arts list",
    "twin_daggers":          "Twin Daggers weapon stats, Photon Arts list",
    "dual_blades":           "Dual Blades weapon stats, Photon Arts list",
    "knuckles":              "Knuckles weapon stats, Photon Arts list",
    "katana":                "Katana weapon stats, Photon Arts list",
    "assault_rifle":         "Assault Rifle weapon stats, Photon Arts list",
    "twin_machine_guns":     "Twin Machine Guns weapon stats, Photon Arts list",
    "talis":                 "Talis weapon stats, Photon Arts/Technique support list",
    "wand":                  "Wand weapon stats, Photon Arts list",
    "harmonizer":            "Harmonizer (Takt) weapon stats, Photon Arts, Waker pet interactions",
    "jet_boots":             "Jet Boots weapon stats, Photon Arts list",
    "weapon_camouflage":     "Weapon camouflage cosmetics, how weapon skins work",

    # Mechanics
    "armor":                 "Armor units, defensive gear stats, armor sets",
    "skill_rings":           "Skill Rings, ring types, ring effects, how to equip",
    "equipment_enhancement": "Equipment enhancement, grinding weapons and armor, enhancement levels",
    "limit_breaking":        "Item limit breaking, raising enhancement caps, limit break materials",
    "techniques":            "Elemental techniques, magic spells, technique types, Photon Blast",
    "augments":              "Augments, special abilities, affixing, capsules, augment effects",
    "addon_skills":          "Add-on skill system, how to unlock and equip add-on skills",
    "creative_space":        "Creative Space, housing, room decorations, CAST customization",
    "quick_food":            "Quick Food Stand, buff recipes, food effects, stat boosts",

    # World / Quests
    "tasks":                 "Main tasks, side quests, daily/weekly tasks, ARCS tasks",
    "urgent_quests":         "Urgent quests, emergency quests, raid schedules, occurrence times",
    "regions":               "Halpha regions, area maps, Aelio, Retem, Kvaris, Stia, Mediora, Ritem, Airio",
    "battledia":             "Battledia trigger quests, yellow/red/blue Battledia",
    "duel_quests":           "Duel Quests, solo boss challenges",
    "leciel_exploration":    "Leciel Exploration quests, floating structure, Leciel rewards",
    "gathering":             "Gathering, field materials, ore, fruit, fishing, farming",
    "titles":                "Titles, achievements, title rewards, title unlock conditions",

    # Lore
    "main_story":            "Main story chapters, main quest progression, story summaries",
    "npc_profiles":          "NPC profiles, character lore, affiliations, ARKS members",
    "worldview_settings":    "World lore, background settings, Halpha environment, ARKS history",
    "glossary_terms":        "In-universe vocabulary, lore glossary, term definitions",
    "arks_chronology":       "ARKS historical chronicles, timeline of events, Halpha history",

    # Enemies
    "enemy_data":            "Enemy species, boss data, DOLLS types, enemy stats and locations",
}

# ==========================================
# INTELLIGENT AI ROUTING LOGIC
# ==========================================
async def route_user_query_ai(client, question_text):
    """
    Uses Gemini to semantically match the user's question to the best
    knowledge base file key, using ROUTING_HINTS as context for each key.
    """
    if not LOCAL_FILE_MAP:
        return None

    available_keys = list(LOCAL_FILE_MAP.keys())

    # Build a compact hint block for the router
    hint_lines = "\n".join(
        f'  "{k}": {ROUTING_HINTS.get(k, "General game data")}' for k in available_keys
    )

    router_prompt = f"""You are a database routing assistant for a PSO2: New Genesis (NGS) knowledge base.
Select the single most relevant file key from the list below to answer the user's question.

User Question: "{question_text}"

Available file keys and what they contain:
{hint_lines}

Rules:
- Match as specifically as possible. If they ask about a specific weapon type, class, or mechanic, prefer that exact file over a general one.
- For current events, banners, or patch notes → prefer "sega_live_feed" or "frontpage".
- For urgent/emergency quest schedules → prefer "urgent_quests".
- For lore questions about the story or NPCs → prefer "main_story", "npc_profiles", or "worldview_settings".
- For augment capsules or affixing → prefer "augments".
- For grinding/enhancement → prefer "equipment_enhancement" or "limit_breaking".
- Only fall back to "frontpage" if truly nothing else fits.
"""

    try:
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
                            "description": "The exact file key from the allowed keys list."
                        }
                    },
                    "required": ["selected_key"]
                },
                temperature=0.0
            )
        )

        result = json.loads(response.text)
        chosen_key = result.get("selected_key")

        if chosen_key in LOCAL_FILE_MAP:
            print(f"🤖 Router: '{question_text[:60]}' ──► [{chosen_key}]", flush=True)
            return LOCAL_FILE_MAP[chosen_key]

    except APIError as api_err:
        raise api_err
    except Exception as e:
        print(f"⚠️ Router non-API error: {e}. Falling back to frontpage.", flush=True)

    return LOCAL_FILE_MAP.get("frontpage") or list(LOCAL_FILE_MAP.values())[0]

# ==========================================
# LIGHTWEIGHT PORT KEEP-ALIVE SERVER
# ==========================================
async def handle_render_ping(reader, writer):
    """Simple HTTP responder for Render's deployment port health checks."""
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

    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)

        try:
            # Step 1: Route the query to the best knowledge base file
            target_file_path = await route_user_query_ai(client, question)
            if not target_file_path:
                await ctx.reply("Wait— I don't even know which part of my notes covers that. Can you be a bit more specific?")
                return

            # Step 2: Load the knowledge base context
            try:
                with open(target_file_path, "r", encoding="utf-8") as f:
                    context_data = f.read()
            except Exception as e:
                print(f"❌ File read failed for {target_file_path}: {e}", flush=True)
                await ctx.reply("Ugh, I went to grab my notes and they were just... gone. Something's wrong with the file system.")
                return

            # Step 3: Generate the answer with Hafu's personality
            response = await client.aio.models.generate_content(
                model=SELECTED_MODEL,
                contents=[
                    f"CONTEXT DATABASE:\n{context_data}",
                    f"User Question: {question}"
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.65,
                    max_output_tokens=900
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
                print(f"⚠️ Key [{idx+1}] hit status {api_err.code}. Rotating to next key...", flush=True)
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

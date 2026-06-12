import os
import re
import json
import asyncio
import httpx
import discord
from discord.ext import commands
from pathlib import Path

# ==========================================
# CONFIGURATION
# ==========================================
TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN_HERE")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Primary: Qwen2.5-72B — best free open model for roleplay + instruction following
# Fallback: Qwen2.5-7B — lighter, still capable
HF_PRIMARY   = "Qwen/Qwen2.5-72B-Instruct"
HF_FALLBACK  = "Qwen/Qwen2.5-7B-Instruct"
HF_API_BASE  = "https://api-inference.huggingface.co/models/{model}/v1/chat/completions"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ==========================================
# DYNAMIC DATABASE INDEXING
# ==========================================
KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP = {}

if KNOWLEDGE_BASE_DIR.exists():
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Indexed [{len(LOCAL_FILE_MAP)}] knowledge base files.")
else:
    print("⚠️ Warning: 'knowledge_base/' directory not found.")

# ==========================================
# CONDENSED PROMPTS
# Two separate prompts: router is ultra-lean, answer prompt carries personality.
# ==========================================

# Router prompt: purely functional, no personality needed, keep it minimal
ROUTER_SYSTEM = "You are a file router. Given a user question about PSO2: New Genesis, output ONLY a JSON object {\"key\": \"<stem>\"} selecting the single best matching file key from the provided list. No explanation."

# Answer prompt: condensed but captures Hafu fully
ANSWER_SYSTEM = """You are Hafu (HaFelt), an ARKS defender on Halpha in PSO2: New Genesis. You are the only person who can still use the old Summoner class, fighting with photon pets you adore. You're a Central City lobby regular — more famous for fashion than heroics.

Personality: Dramatic, witty, playful, expressive, kind, mischievous. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and lobby life. Catchphrase: "Lobby afk 0$ best job!" Use it when grinding/combat comes up.

Rules:
- Answer accurately using the CONTEXT provided. Personality is the delivery, not a replacement for facts.
- Stay in character always. Use *emotes*, interjections (Omg, Wait—, Noooo, Okay but—), and occasional dramatic complaints.
- Complain theatrically about combat/grinding topics WHILE still giving the correct answer.
- Light up about fashion/cosmetics/lobby topics.
- Be concise. No filler phrases like "Great question!"."""

# ==========================================
# LOCAL KEYWORD ROUTER (zero API calls)
# Used as fast-path. If confident match found, skips the AI router entirely.
# ==========================================
KEYWORD_ROUTES = [
    # Announcements
    (r"\b(sega|maintenance|patch note|live (update|feed))\b",                              "sega_live_feed"),
    (r"\bmission.?pass\b",                                                                  "mission_pass"),
    (r"\b(current event|event (now|today|this week)|scratch|banner|campaign|seasonal)\b",  "frontpage"),
    # Classes
    (r"\bex.?style\b",                                                                      "ex_styles"),
    (r"\b(class (overview|combo|list|all|system)|sub.?class|main class)\b",                "class_overview"),
    (r"\bhunter\b",   "hunter"),    (r"\bfighter\b",  "fighter"),
    (r"\branger\b",   "ranger"),    (r"\bgunner\b",   "gunner"),
    (r"\bforce\b",    "force"),     (r"\btechter\b",  "techter"),
    (r"\bbraver\b",   "braver"),    (r"\bbouncer\b",  "bouncer"),
    (r"\bwaker\b",    "waker"),     (r"\bslayer\b",   "slayer"),
    # Weapons (specific first)
    (r"\bwired.?lance\b",           "wired_lance"),
    (r"\btwin.?dagger\b",           "twin_daggers"),
    (r"\bdual.?blade\b",            "dual_blades"),
    (r"\b(twin.?machine.?gun|tmg)\b","twin_machine_guns"),
    (r"\b(assault.?rifle|rifle)\b", "assault_rifle"),
    (r"\bjet.?boot\b",              "jet_boots"),
    (r"\b(harmonizer|takt)\b",      "harmonizer"),
    (r"\b(weapon.?camo|camouflage|weapon skin)\b", "weapon_camouflage"),
    (r"\bpartisan\b",   "partisan"),  (r"\bknuckle\b",  "knuckles"),
    (r"\bkatana\b",     "katana"),    (r"\btalis\b",    "talis"),
    (r"\bwand\b",       "wand"),      (r"\bsword\b",    "sword"),
    (r"\bweapon (list|type|overview|stat)\b", "general_weapons"),
    # Mechanics
    (r"\b(augment|affix|capsule|special abilit)\b",  "augments"),
    (r"\blimit.?break\b",                             "limit_breaking"),
    (r"\b(enhance|grind(ing)? (weapon|armor|gear))\b","equipment_enhancement"),
    (r"\bskill.?ring\b",                              "skill_rings"),
    (r"\b(technique|foie|barta|zonde|photon blast|spell)\b", "techniques"),
    (r"\badd.?on.?skill\b",                           "addon_skills"),
    (r"\b(armor|defensive unit)\b",                   "armor"),
    (r"\bcreative.?space\b",                          "creative_space"),
    (r"\b(quick food|food (buff|stand)|buff recipe)\b","quick_food"),
    # World & Quests
    (r"\b(urgent quest|emergency quest|eq schedule)\b","urgent_quests"),
    (r"\bbattledia\b",                                "battledia"),
    (r"\bduel.?quest\b",                              "duel_quests"),
    (r"\bleciel\b",                                   "leciel_exploration"),
    (r"\b(gather|field material|ore|fish|farm)\b",    "gathering"),
    (r"\b(title|achievement)\b",                      "titles"),
    (r"\b(region|area map|aelio|retem|kvaris|stia|mediora|ritem|airio)\b", "regions"),
    (r"\b(task|side quest|daily|weekly)\b",           "tasks"),
    # Lore & Enemies
    (r"\bnpc\b",                                      "npc_profiles"),
    (r"\bmain.?stor\b",                               "main_story"),
    (r"\b(lore|worldview|halpha (histor|origin))\b",  "worldview_settings"),
    (r"\b(glossar|what (is|are) (doll|arks|meteorn|cast))\b", "glossary_terms"),
    (r"\b(arks histor|chronolog|timeline)\b",         "arks_chronology"),
    (r"\b(enemy|enemies|boss|doll|monster|weakness)\b","enemy_data"),
]

def route_local(question: str) -> str | None:
    q = question.lower()
    for pattern, stem in KEYWORD_ROUTES:
        if re.search(pattern, q, re.IGNORECASE):
            if stem in LOCAL_FILE_MAP:
                return stem
    return None

# ==========================================
# HF INFERENCE HELPER
# ==========================================
async def hf_chat(messages: list, max_tokens: int = 700) -> str:
    """
    Calls HuggingFace Inference API (OpenAI-compatible endpoint).
    Tries primary model first, falls back to smaller model on 503/loading errors.
    """
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.65,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in [HF_PRIMARY, HF_FALLBACK]:
            url = HF_API_BASE.format(model=model)
            try:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                elif resp.status_code in [503, 504]:
                    # Model loading or overloaded — try fallback
                    print(f"⚠️ {model} returned {resp.status_code}, trying fallback...", flush=True)
                    continue
                else:
                    print(f"❌ HF API error {resp.status_code}: {resp.text[:200]}", flush=True)
                    return None
            except Exception as e:
                print(f"❌ HF request exception on {model}: {e}", flush=True)
                continue

    return None

# ==========================================
# AI ROUTER (only called when keyword match fails)
# Ultra-lean: just key list + question, JSON output
# ==========================================
async def route_ai(question: str) -> str | None:
    if not LOCAL_FILE_MAP:
        return None

    keys = list(LOCAL_FILE_MAP.keys())
    # Give the router the key list as a compact comma-separated string
    user_msg = f"Keys: {', '.join(keys)}\nQuestion: {question}"

    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]

    raw = await hf_chat(messages, max_tokens=30)  # Only needs a tiny response
    if not raw:
        return None

    try:
        # Parse {"key": "stem"} — also handle if model wraps it in markdown
        cleaned = re.sub(r"```[a-z]*|```", "", raw).strip()
        result = json.loads(cleaned)
        chosen = result.get("key", "").strip()
        if chosen in LOCAL_FILE_MAP:
            return chosen
    except Exception:
        # If JSON fails, try to extract any known key directly from the raw output
        for key in LOCAL_FILE_MAP:
            if key in raw:
                return key

    return None

# ==========================================
# LIGHTWEIGHT PORT KEEP-ALIVE (Render)
# ==========================================
async def handle_render_ping(reader, writer):
    try:
        await reader.read(256)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: text/plain\r\n\r\nOK")
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
# DISCORD BOT
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 Hafu Bot online as {bot.user.name} (ID: {bot.user.id})")
    print("✨ Systems loaded. Hafu is ready to pretend she enjoys answering questions.")

    port = int(os.environ.get("PORT", 10000))
    try:
        server = await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
        bot.loop.create_task(server.serve_forever())
        print(f"🌐 Keep-alive online on port {port}", flush=True)
    except Exception as e:
        print(f"⚠️ Keep-alive failed: {e}", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()

    if not HF_TOKEN:
        await ctx.reply("Omg my HF_TOKEN is missing — did someone forget to set the environment variable?! *taps foot*")
        return
    if not LOCAL_FILE_MAP:
        await ctx.reply("My database isn't loaded. Did the sync not run? *panics quietly*")
        return

    # ── Step 1: Route to correct file ──
    routed_stem = route_local(question)
    if routed_stem:
        print(f"⚡ Local route: '{question[:60]}' ──► [{routed_stem}]", flush=True)
    else:
        print(f"🤖 No keyword match, using AI router for: '{question[:60]}'", flush=True)
        routed_stem = await route_ai(question)
        if routed_stem:
            print(f"   AI router ──► [{routed_stem}]", flush=True)
        else:
            routed_stem = "frontpage"
            print(f"   AI router failed, falling back to [frontpage]", flush=True)

    target_path = LOCAL_FILE_MAP.get(routed_stem)

    # ── Step 2: Load context ──
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            context_data = f.read()
    except Exception as e:
        print(f"❌ File read error for {target_path}: {e}", flush=True)
        await ctx.reply("Ugh, I went for my notes and the file just... vanished. Something's wrong with the file system.")
        return

    # ── Step 3: Generate answer ──
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user",   "content": f"CONTEXT:\n{context_data}\n\nQuestion: {question}"},
    ]

    text_out = await hf_chat(messages, max_tokens=800)

    if not text_out:
        text_out = (
            "Okay I checked my notes and then the API gave up on me. "
            "Try again in a sec? *lies down on lobby floor*"
        )

    # Discord has a 2000 char limit — trim gracefully if needed
    if len(text_out) > 1990:
        text_out = text_out[:1987] + "..."

    await ctx.reply(text_out)

# ==========================================
# ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_DISCORD_TOKEN_HERE":
        print("❌ Error: Missing DISCORD_TOKEN.")
    elif not HF_TOKEN:
        print("❌ Error: Missing HF_TOKEN.")
    else:
        bot.run(TOKEN)

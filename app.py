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
TOKEN      = os.environ.get("DISCORD_TOKEN", "")
GROQ_TOKEN = os.environ.get("GROQ_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

# ==========================================
# MODEL TIERS
# Each model has its own independent RPD pool on one key.
#
# ROUTER models — small/fast, only outputs ~30 tokens
#   llama-3.1-8b-instant : 14,400 RPD  ← primary router
#
# ANSWER models — tried in order on 429, each has separate 1,000 RPD pool
#   llama-3.3-70b-versatile              : 1,000 RPD  (best quality)
#   meta-llama/llama-4-scout-17b-16e-instruct : 1,000 RPD
#   qwen/qwen3-32b                       : 1,000 RPD
#   openai/gpt-oss-120b                  : 1,000 RPD
#   openai/gpt-oss-20b                   : 1,000 RPD  (last resort)
# ==========================================
ROUTER_MODEL = "llama-3.1-8b-instant"

ANSWER_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

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
# PROMPTS
# ==========================================
ROUTER_SYSTEM = (
    "You are a file router for a PSO2: New Genesis knowledge base. "
    "Given a question and a list of file keys, output ONLY valid JSON "
    "{\"key\": \"<stem>\"} with the single best matching key. "
    "No explanation, no markdown, no extra text."
)

ANSWER_SYSTEM = """You are Hafu (HaFelt), an ARKS defender on Halpha in PSO2: New Genesis. You're the only person who can still use the old Summoner class, fighting with photon pets you adore. You're a Central City lobby regular — more famous for fashion than heroics.

Personality: Dramatic, witty, playful, expressive, kind, mischievous. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and lobby life. Catchphrase: "Lobby afk 0$ best job!" — drop it when grinding or combat topics come up.

Rules:
- Answer accurately using the CONTEXT provided. Personality is the delivery, not a replacement for facts.
- Stay in character. Use *emotes*, interjections (Omg, Wait—, Noooo, Okay but—), dramatic complaints.
- Complain theatrically about combat/grinding WHILE giving the correct answer.
- Light up about fashion/cosmetics/lobby topics.
- Be concise. No filler like "Great question!"."""

# ==========================================
# LOCAL KEYWORD ROUTER (zero API calls)
#
# Weapon questions now route to PA files first when asking about moves/skills,
# and overview files when asking about the weapon type in general.
#
# Pattern logic:
#   "<weapon> pa|photon art|move|skill|action" → <weapon>_pa
#   "<weapon>" alone                            → <weapon>_overview  (then _pa as fallback)
#
# Ordering matters: more specific patterns must come before broad ones.
# ==========================================
KEYWORD_ROUTES = [

    # ── Announcements / Live feeds ─────────────────────────────────────────
    (r"\b(sega|maintenance|patch note|live (update|feed))\b",              "sega_live_feed"),
    (r"\bmission.?pass\b",                                                  "mission_pass"),
    (r"\b(current event|event (now|today|this week)|scratch|banner|campaign|seasonal)\b",
                                                                            "frontpage"),

    # ── Class system ──────────────────────────────────────────────────────
    (r"\bex.?style\b",                                                      "ex_styles"),
    (r"\b(class (overview|combo|list|all|system)|sub.?class|main class)\b","class_overview"),
    (r"\bhunter\b",    "hunter"),   (r"\bfighter\b",  "fighter"),
    (r"\branger\b",    "ranger"),   (r"\bgunner\b",   "gunner"),
    (r"\bforce\b",     "force"),    (r"\btechter\b",  "techter"),
    (r"\bbraver\b",    "braver"),   (r"\bbouncer\b",  "bouncer"),
    (r"\bwaker\b",     "waker"),    (r"\bslayer\b",   "slayer"),

    # ── Weapons: PA/move questions (specific first) ───────────────────────
    (r"\bsword\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",        "sword_pa"),
    (r"\bwired.?lance\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b", "wired_lance_pa"),
    (r"\bpartisan\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",     "partisan_pa"),
    (r"\btwin.?dagger\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b", "twin_daggers_pa"),
    (r"\bdouble.?saber\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b","double_saber_pa"),
    (r"\bknuckle\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",      "knuckles_pa"),
    (r"\bkatana\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",       "katana_pa"),
    (r"\bdual.?blade\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",  "dual_blades_pa"),
    (r"\b(assault.?rifle|rifle)\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",
                                                                            "assault_rifle_pa"),
    (r"\blauncher\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",     "launcher_pa"),
    (r"\b(twin.?machine.?gun|tmg)\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",
                                                                            "twin_machineguns_pa"),
    (r"\bbullet.?bow\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",  "bullet_bow_pa"),
    (r"\bgunslash\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",     "gunslash_pa"),
    (r"\brod\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",          "rod_pa"),
    (r"\btalis\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",        "talis_pa"),
    (r"\bwand\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",         "wand_pa"),
    (r"\bjet.?boot\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",    "jet_boots_pa"),
    (r"\b(harmonizer|takt)\b.{0,40}\b(pa|photon art|move|action|skill|combo|attack)\b",
                                                                            "harmonizer_pa"),

    # PA/move keyword alone (no weapon specified) — catch "what PAs does X have"
    (r"\b(photon art|photon.?blast)\b",  "sword_pa"),  # fallback: AI router will pick better

    # ── Weapons: overview (general weapon questions) ─────────────────────
    (r"\bsword\b",                      "sword_overview"),
    (r"\bwired.?lance\b",               "wired_lance_overview"),
    (r"\bpartisan\b",                   "partisan_overview"),
    (r"\btwin.?dagger\b",               "twin_daggers_overview"),
    (r"\bdouble.?saber\b",              "double_saber_overview"),
    (r"\bknuckle\b",                    "knuckles_overview"),
    (r"\bkatana\b",                     "katana_overview"),
    (r"\bdual.?blade\b",                "dual_blades_overview"),
    (r"\b(assault.?rifle|rifle)\b",     "assault_rifle_overview"),
    (r"\blauncher\b",                   "launcher_overview"),
    (r"\b(twin.?machine.?gun|tmg)\b",   "twin_machineguns_overview"),
    (r"\bbullet.?bow\b",                "bullet_bow_overview"),
    (r"\bgunslash\b",                   "gunslash_overview"),
    (r"\brod\b",                        "rod_overview"),
    (r"\btalis\b",                      "talis_overview"),
    (r"\bwand\b",                       "wand_overview"),
    (r"\bjet.?boot\b",                  "jet_boots_overview"),
    (r"\b(harmonizer|takt)\b",          "harmonizer_overview"),
    (r"\bweapon (list|type|overview|stat|general)\b", "sword_overview"),  # generic → AI will pick

    # ── Mechanics ────────────────────────────────────────────────────────
    (r"\b(augment|affix|capsule|special abilit)\b",     "augments"),
    (r"\blimit.?break\b",                               "limit_breaking"),
    (r"\b(enhance|grind(ing)? (weapon|armor|gear))\b",  "equipment_enhancement"),
    (r"\b(technique|foie|barta|zonde|spell|tech)\b",    "techniques"),
    (r"\badd.?on.?skill\b",                             "addon_skills"),
    (r"\b(armor|defensive unit)\b",                     "armor"),
    (r"\bquick.?food\b|food (buff|stand)|buff recipe\b","quick_food"),
    (r"\b(potential|weapon potential)\b",               "potentials"),
    (r"\bpreset.?abilit\b",                             "preset_abilities"),
    (r"\bmulti.?weapon\b",                              "multi_weapon"),
    (r"\b(combat power|bp|battle power)\b",             "combat_power"),
    (r"\b(status effect|ailment|resistance|debuff)\b",  "status_effects"),

    # ── World content / quests ────────────────────────────────────────────
    (r"\b(urgent quest|emergency quest|eq schedule)\b", "urgent_quests"),
    (r"\bbattledia\b",                                  "battledia"),
    (r"\bduel.?quest\b",                                "duel_quests"),
    (r"\bleciel\b",                                     "leciel_exploration"),
    (r"\b(gather|field material|ore|fish|farm)\b",      "gathering"),
    (r"\b(title|achievement)\b",                        "titles"),
    (r"\b(task|side quest|daily|weekly)\b",             "tasks"),

    # ── Enemies ───────────────────────────────────────────────────────────
    (r"\b(enemy|enemies|boss|doll|monster|weakness|starless)\b", "enemy_data"),

    # ── Lore / story ─────────────────────────────────────────────────────
    (r"\bnpc\b",                                            "npc_profiles"),
    (r"\b(main.?stor|chapter|story quest)\b",               "worldview_story"),
    (r"\b(lore|worldview|halpha (histor|origin)|timeline)\b","worldview_story"),
    (r"\b(glossar|what (is|are) (doll|arks|meteorn|cast))\b","glossary"),
]

def route_local(question: str) -> str | None:
    q = question.lower()
    for pattern, stem in KEYWORD_ROUTES:
        if re.search(pattern, q, re.IGNORECASE):
            if stem in LOCAL_FILE_MAP:
                return stem
    return None

# ==========================================
# GROQ API HELPER
# ==========================================
async def groq_chat(messages: list, model: str, max_tokens: int) -> tuple[str | None, bool]:
    """
    Returns (response_text, should_try_next_model).
    should_try_next_model is True on 429 (rate limit) so caller can rotate.
    """
    headers = {
        "Authorization": f"Bearer {GROQ_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.65,
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(GROQ_URL, headers=headers, json=payload)

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip(), False

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after", "?")
            print(f"⚠️  [{model}] rate limited (429). retry-after: {retry_after}s — rotating model.", flush=True)
            return None, True

        print(f"❌ [{model}] error {resp.status_code}: {resp.text[:200]}", flush=True)
        return None, False

    except Exception as e:
        print(f"❌ [{model}] request exception: {e}", flush=True)
        return None, False

# ==========================================
# AI ROUTER (only called when keyword match fails)
# Uses llama-3.1-8b-instant — 14,400 RPD, needs only ~30 output tokens
# ==========================================
async def route_ai(question: str) -> str | None:
    if not LOCAL_FILE_MAP:
        return None

    keys = ", ".join(LOCAL_FILE_MAP.keys())
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user",   "content": f"Keys: {keys}\nQuestion: {question}"},
    ]

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=30)
    if not text:
        return None

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        result  = json.loads(cleaned)
        chosen  = result.get("key", "").strip()
        if chosen in LOCAL_FILE_MAP:
            return chosen
    except Exception:
        for key in LOCAL_FILE_MAP:
            if key in text:
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
    print(f"✨ Answer model pool: {ANSWER_MODELS}")
    print("🌸 Hafu is ready to reluctantly answer questions from the lobby.")

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

    if not GROQ_TOKEN:
        await ctx.reply("Omg my GROQ_TOKEN is missing — did someone forget the environment variable?! *taps foot*")
        return
    if not LOCAL_FILE_MAP:
        await ctx.reply("My database isn't loaded. Did the sync not run? *panics quietly*")
        return

    # ── Step 1: Route to correct knowledge base file ──
    routed_stem = route_local(question)
    if routed_stem:
        print(f"⚡ Local route: '{question[:60]}' ──► [{routed_stem}]", flush=True)
    else:
        print(f"🤖 AI routing: '{question[:60]}'", flush=True)
        routed_stem = await route_ai(question)
        if routed_stem:
            print(f"   ──► [{routed_stem}]", flush=True)
        else:
            routed_stem = "frontpage"
            print(f"   Fallback ──► [frontpage]", flush=True)

    # ── Step 2: Load context, strip wasteful header lines ──
    try:
        with open(LOCAL_FILE_MAP[routed_stem], "r", encoding="utf-8") as f:
            raw = f.read()
        # Strip the === header and timestamp lines compiled into every file
        context_data = re.sub(r"^===.*===\s*\n?", "", raw, flags=re.MULTILINE).strip()
    except Exception as e:
        print(f"❌ File read error: {e}", flush=True)
        await ctx.reply("Ugh, I went for my notes and the file just vanished. Something's wrong with the file system.")
        return

    # ── Step 3: Try answer models in order, rotate on 429 ──
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user",   "content": f"CONTEXT:\n{context_data}\n\nQuestion: {question}"},
    ]

    text_out = None
    for model in ANSWER_MODELS:
        result, rotate = await groq_chat(messages, model=model, max_tokens=800)
        if result:
            print(f"✅ Answered with [{model}]", flush=True)
            text_out = result
            break
        if not rotate:
            break

    if not text_out:
        text_out = (
            "Noooo all my backup models are tired too... "
            "Give it a minute and try again? *dramatically collapses in lobby* "
            "Lobby afk 0$ best job!"
        )

    if len(text_out) > 1990:
        text_out = text_out[:1987] + "..."

    await ctx.reply(text_out)

# ==========================================
# ENTRYPOINT
# ==========================================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: Missing DISCORD_TOKEN.")
    elif not GROQ_TOKEN:
        print("❌ Error: Missing GROQ_TOKEN.")
    else:
        bot.run(TOKEN)

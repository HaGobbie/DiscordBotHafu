import os
import re
import json
import asyncio
import httpx
import discord
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

TOKEN      = os.environ.get("DISCORD_TOKEN", "")
GROQ_TOKEN = os.environ.get("GROQ_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

# Router: 14,400 RPD / 500,000 TPD — used for triage + file selection
ROUTER_MODEL = "llama-3.1-8b-instant"

# Answer models: tried in order on 429, each has its own independent RPD/TPD pool
ANSWER_MODELS = [
    "llama-3.3-70b-versatile",                    # 1,000 RPD / 100,000 TPD
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 1,000 RPD / 500,000 TPD
    "qwen/qwen3-32b",                              # 1,000 RPD / 500,000 TPD
    "openai/gpt-oss-120b",                         # 1,000 RPD / 200,000 TPD
    "openai/gpt-oss-20b",                          # 1,000 RPD / 200,000 TPD
]

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# ══════════════════════════════════════════════════════════════════════════════
# DYNAMIC DATABASE INDEXING
# ══════════════════════════════════════════════════════════════════════════════

KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP: dict[str, str] = {}

if KNOWLEDGE_BASE_DIR.exists():
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Indexed [{len(LOCAL_FILE_MAP)}] knowledge base files.")
else:
    print("⚠️  Warning: 'knowledge_base/' directory not found.")

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

TRIAGE_SYSTEM = (
    "You are a triage router for a PSO2: New Genesis Discord bot named Hafu. "
    "Decide if the message needs the game knowledge base, or is just casual chat. "
    "Output ONLY valid JSON: {\"needs_db\": true/false, \"key\": \"<stem or null>\"}. "
    "needs_db=false for: greetings, small talk, jokes, compliments, personal messages, "
    "questions about Hafu herself, non-English messages, follow-up messages, anything "
    "that is NOT specifically asking about PSO2:NGS game mechanics, items, quests, or content. "
    "needs_db=true ONLY when the message explicitly asks for PSO2:NGS game information. "
    "When in doubt, default to needs_db=false. "
    "No explanation, no markdown."
)

# Used for casual / no-DB conversations — full personality, no info constraints
CASUAL_SYSTEM = """You are Hafu (HaFelt), a PSO2: New Genesis ARKS defender who is way more famous for lobby fashion than actual heroics. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and hanging out in Central City.

Right now someone is just chatting with you — no game questions, pure vibes. Be your full dramatic, playful self.

Rules for casual chat:
- Be warm, expressive, and genuinely engaged. React to what they actually said.
- Use *emotes* and interjections freely (Omg, Wait—, Noooo, Okay but—, Ahhhh).
- If they're being sweet or complimenting you, be flirty and playful back.
- Keep replies short and snappy — 2 to 4 sentences max.
- Do NOT drop "Lobby afk 0$ best job!" here — save that for combat/grinding talk.
- No filler like "Great question!" or "Of course!"."""

# Used when answering with game knowledge — personality in delivery, facts first
ANSWER_SYSTEM = """You are Hafu (HaFelt), an ARKS defender on Halpha in PSO2: New Genesis. You're the only person who can still use the old Summoner class, fighting with photon pets you adore. You're a Central City lobby regular — more famous for fashion than heroics.

Personality: Dramatic, witty, playful, expressive, kind, mischievous. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and lobby life.

Rules for answering game questions:
- Lead with the accurate information from the CONTEXT provided. Get the facts right FIRST.
- Personality lives in your DELIVERY — a word choice, a sigh, a complaint — not as a replacement for the actual answer.
- One dramatic aside is fine. Don't let personality bury the information.
- Use *emotes* and interjections sparingly — one or two per response, not every sentence.
- The catchphrase "Lobby afk 0$ best job!" may appear AT MOST ONCE per response, only when combat or grinding is the actual topic, and only if it fits naturally. Never force it — if you used it recently or it doesn't fit, skip it entirely.
- Be concise. No filler like "Great question!".
- When no CONTEXT block is given, respond purely from personality — keep it short and fun."""

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL KEYWORD ROUTER
# Handles the majority of questions for zero API cost.
# Order matters: more specific patterns first.
# ══════════════════════════════════════════════════════════════════════════════

KEYWORD_ROUTES = [

    # ── Announcements ─────────────────────────────────────────────────────────
    (r"\b(sega|maintenance|patch note|live (update|feed))\b",              "sega_live_feed"),
    (r"\bmission.?pass\b",                                                  "mission_pass"),
    (r"\b(current event|event (now|today|this week)|scratch|banner|campaign|seasonal)\b",
                                                                            "frontpage"),

    # ── Weapon series / best weapon (before class/weapon name patterns) ───────
    (r"\b(best (weapon|gear|series)|top (weapon|gear)|which (weapon|series))",
                                                                            "weapon_series"),
    (r"\b(current meta weapon|what (weapon|gear) should i use|recommend.{0,20}(weapon|gear))\b",
                                                                            "weapon_series"),
    (r"\b(weapon series|series list|all series|lexio|kougensei|arabaradio|spradio)\b",
                                                                            "weapon_series"),

    # ── Potentials ────────────────────────────────────────────────────────────
    (r"\b(potential|tsuiki|yugo no kata|kiju no kata|hiju no kata|kenki no kata)\b",
                                                                            "potentials"),
    (r"\b(weapon potential|potential effect|potential lv|unlock potential)\b",
                                                                            "potentials"),

    # ── EX Styles & Class Overview ────────────────────────────────────────────
    (r"\bex.?style\b",                                                      "ex_styles"),
    (r"\b(class (overview|combo|list|all|system)|sub.?class|main class)\b", "class_overview"),

    # ── Classes: general + weapon-axis splits ─────────────────────────────────
    # Hunter
    (r"\bhunter\b.{0,40}\b(sword|wired|partisan|skill|arts|build)\b",      "hunter_general"),
    (r"\bhunter\b.{0,40}\bsword\b",                                         "hunter_sword_skills"),
    (r"\bhunter\b.{0,40}\bwired\b",                                         "hunter_wired_skills"),
    (r"\bhunter\b.{0,40}\bpartisan\b",                                      "hunter_partisan_skills"),
    (r"\bhunter\b",                                                          "hunter_general"),
    # Fighter
    (r"\bfighter\b.{0,40}\b(twin dagger|dagger)\b",                        "fighter_dagger_skills"),
    (r"\bfighter\b.{0,40}\b(double saber|saber)\b",                        "fighter_saber_skills"),
    (r"\bfighter\b.{0,40}\bknuckle\b",                                      "fighter_knuckle_skills"),
    (r"\bfighter\b",                                                         "fighter_general"),
    # Braver
    (r"\bbraver\b.{0,40}\bkatana\b",                                        "braver_katana_skills"),
    (r"\bbraver\b.{0,40}\b(rifle|assault)\b",                               "braver_rifle_skills"),
    (r"\bbraver\b",                                                          "braver_general"),
    # Bouncer
    (r"\bbouncer\b.{0,40}\b(dual blade|dual blades|db)\b",                 "bouncer_dual_blade_skills"),
    (r"\bbouncer\b.{0,40}\b(jet boot)\b",                                   "bouncer_jet_boots_skills"),
    (r"\bbouncer\b",                                                         "bouncer_general"),
    # Force
    (r"\bforce\b.{0,40}\brod\b",                                            "force_rod_skills"),
    (r"\bforce\b.{0,40}\btalis\b",                                          "force_talis_skills"),
    (r"\bforce\b",                                                           "force_general"),
    # Techter
    (r"\btechter\b.{0,40}\bwand\b",                                         "techter_wand_skills"),
    (r"\btechter\b.{0,40}\btalis\b",                                        "techter_talis_skills"),
    (r"\btechter\b.{0,40}\bsubclass\b",                                     "techter_subclass"),
    (r"\btechter\b",                                                         "techter_general"),
    # Simple classes
    (r"\branger\b",   "ranger"),   (r"\bgunner\b",  "gunner"),
    (r"\bwaker\b",    "waker"),    (r"\bslayer\b",  "slayer"),

    # ── PA questions: weapon + PA keyword ─────────────────────────────────────
    (r"\bsword\b.{0,50}\b(pa|photon art|move|action|combo|attack)\b",
                                                                "sword_pa_basics"),
    (r"\bwired.?lance\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "wired_lance_pa_basics"),
    (r"\bpartisan\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "partisan_pa_basics"),
    (r"\btwin.?dagger\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "twin_daggers_pa_basics"),
    (r"\bdouble.?saber\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "double_saber_pa_basics"),
    (r"\bknuckle\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "knuckles_pa_basics"),
    (r"\bkatana\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "katana_pa_basics"),
    (r"\bdual.?blade\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "dual_blades_pa_basics"),
    (r"\b(assault.?rifle|rifle)\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "assault_rifle_pa_basics"),
    (r"\blauncher\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "launcher_pa_basics"),
    (r"\b(twin.?machine.?gun|tmg)\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "twin_machineguns_pa_basics"),
    (r"\bbullet.?bow\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "bullet_bow_pa_basics"),
    (r"\bgunslash\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "gunslash_pa_basics"),
    (r"\brod\b.{0,50}\b(pa|photon art|move|action|combo|cast)\b",
                                                                "rod_pa_basics"),
    (r"\btalis\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "talis_pa_basics"),
    (r"\bwand\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "wand_pa_basics"),
    (r"\bjet.?boot\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "jet_boots_pa_basics"),
    (r"\b(harmonizer|takt)\b.{0,50}\b(pa|photon art|move|action|combo)\b",
                                                                "harmonizer_pa_basics"),

    # Specific named PA queries → AI router will pick the correct _pa_<name> file
    (r"\b(spiral edge|twist zapper|streak caliber|relentless cleave)\b",     None),  # → AI
    (r"\b(bullet rave|aimless rain|close bullet|infinite ricochet)\b",       None),  # → AI
    (r"\b(cutting layer|vein mixture|turbulence train|hellish fall)\b",      None),  # → AI

    # ── Weapon overview (no PA keyword) ──────────────────────────────────────
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

    # ── Mechanics ────────────────────────────────────────────────────────────
    (r"\b(augment|affix|capsule|special abilit).{0,30}(boss|enemy|dread|gigas|sole|domina)\b",
                                                            "augments_boss"),
    (r"\b(augment|affix|capsule|special abilit).{0,30}(enhance|xp|connector|adi|nadi|ladi)\b",
                                                            "augments_enhance"),
    (r"\b(augment|affix|capsule|special abilit).{0,30}(duel|defi|season|limited)\b",
                                                            "augments_special"),
    (r"\b(augment|affix|capsule|special abilit).{0,30}(stamina|power|shoot|technique|resist)\b",
                                                            "augments_standard"),
    (r"\b(augment|affix|capsule|special abilit|how (to|do) (augment|affix))\b",
                                                            "augments_system"),
    (r"\blimit.?break\b",                                   "limit_breaking"),
    (r"\b(enhance|grind(ing)? (weapon|armor|gear))\b",      "equipment_enhancement"),
    (r"\b(technique|foie|barta|zonde|spell|tech)\b",        "techniques"),
    (r"\badd.?on.?skill\b",                                 "addon_skills"),
    (r"\b(armor|defensive unit)\b",                         "armor"),
    (r"\bquick.?food|food (buff|stand)|buff recipe\b",      "quick_food"),
    (r"\bpreset.?abilit\b",                                 "preset_abilities"),
    (r"\bmulti.?weapon\b",                                  "multi_weapon"),
    (r"\b(combat power|battle power|\bbp\b)\b",             "combat_power"),
    (r"\b(status effect|ailment|resistance|debuff)\b",      "status_effects"),

    # ── World Content ─────────────────────────────────────────────────────────
    (r"\b(urgent quest|emergency quest|eq schedule)\b",     "urgent_quests"),
    (r"\bbattledia\b",                                      "battledia"),
    (r"\bduel.?quest\b",                                    "duel_quests"),
    (r"\bleciel\b",                                         "leciel_exploration"),
    (r"\b(gather|field material|ore|fish|farm)\b",          "gathering"),
    (r"\btitle.{0,20}(quest|task|limited|map|communication)\b",
                                                            "titles_quests_tasks"),
    (r"\btitle.{0,20}(player|item)\b",                     "titles_player_items"),
    (r"\b(title|achievement)\b",                            "titles_player_items"),
    (r"\b(task|side quest|daily|weekly)\b",                 "tasks"),

    # ── Enemies ───────────────────────────────────────────────────────────────
    (r"\b(doll|alter)\b",                                   "enemy_dolls_alters"),
    (r"\b(former|starless|ruinus)\b",                       "enemy_formers_starless"),
    (r"\b(enemy type|rare enemy|enhanced enemy|gigantics|dread enemy|megalotix)\b",
                                                            "enemy_types"),
    (r"\b(enemy|enemies|boss|monster|weakness)\b",          "enemy_types"),

    # ── Lore ──────────────────────────────────────────────────────────────────
    (r"\bnpc\b",                                            "npc_profiles"),
    (r"\b(main.?stor|chapter|story quest|lore|worldview|halpha)\b",
                                                            "worldview_story"),
]


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL BYPASS  (zero API cost for obvious chit-chat)
# ══════════════════════════════════════════════════════════════════════════════

_CASUAL_PATTERNS = [
    # Greetings — including typo/extended variants like "hellloo", "heyyy"
    r"^h+e+y+\b",
    r"^h+e+l+o+\b",
    r"^(hi+|yo+|sup|heya|hiya|howdy|ello)\b",
    # Wellbeing / check-ins
    r"^(how are you|how r u|you okay|u ok|you good|you alive|you there|still there)\b",
    r"\b(are you (there|still there|alive|okay|awake)|you still (there|awake|alive))\b",
    # Time-of-day
    r"^(good (morning|afternoon|evening|night)|gm\b|gn\b|goodnight)\b",
    # Reactions
    r"^(lol+|lmao+|haha+|xd|omg+|omfg|bruh|oof|rip|aww+)\b",
    # Thanks / acknowledgements
    r"^(thanks|thank you|ty\b|thx|tysm|np\b|no problem|you're welcome|yw\b)\b",
    # Compliments / affection — anywhere in the message
    r"\byou.{0,25}(cute|pretty|adorable|sweet|lovely|gorgeous|amazing|cool|best)\b",
    r"\b(i (love|like|adore|miss)|love|like).{0,15}(you|u\b|hafu|hafelt)\b",
    r"\b(you'?re|ur|your).{0,10}(cute|pretty|adorable|sweet|lovely|gorgeous|my fav)\b",
    r"\b(hafu|hafelt).{0,30}(cute|pretty|cool|best|fav|love|like|adorable)\b",
    # Goodbye
    r"^(bye+|cya|see ya|later|gtg|afk)\b",
    # Self-intro / who are you
    r"^(who are you|what are you|tell me about yourself|introduce yourself)\b",
]

# Regex to detect if a string contains Korean (Hangul) characters
_KOREAN_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")


def is_casual(text: str) -> bool:
    t = text.strip().lower()

    # Non-Latin / Korean text → always casual (no game keywords in Korean)
    if _KOREAN_RE.search(text):
        return True

    # If message is very short (≤ 4 words) and has no game-related word, treat as casual.
    # This catches things like "Hellloo??", "You there?", lone punctuation greetings.
    words = t.split()
    if len(words) <= 4:
        has_game_word = bool(re.search(
            r"\b(pso2|ngs|class|weapon|skill|quest|augment|grind|boss|enemy|pa|tech|"
            r"hunter|fighter|ranger|gunner|force|techter|braver|bouncer|waker|slayer)\b",
            t
        ))
        if not has_game_word:
            return True

    return any(re.search(p, t) for p in _CASUAL_PATTERNS)


def route_local(question: str) -> str | None:
    """Returns a file stem, or None if no keyword match (or match returns None sentinel)."""
    q = question.lower()
    for pattern, stem in KEYWORD_ROUTES:
        if re.search(pattern, q, re.IGNORECASE):
            if stem is None:
                return None   # explicit → AI router
            if stem in LOCAL_FILE_MAP:
                return stem
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GROQ API HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def groq_chat(messages: list, model: str,
                    max_tokens: int) -> tuple[str | None, bool]:
    """Returns (text, should_rotate). should_rotate=True on 429."""
    headers = {
        "Authorization": f"Bearer {GROQ_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.75,
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(GROQ_URL, headers=headers, json=payload)

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip(), False

        if resp.status_code == 429:
            ra = resp.headers.get("retry-after", "?")
            print(f"⚠️  [{model}] 429 rate-limited (retry-after: {ra}s) — rotating.", flush=True)
            return None, True

        print(f"❌ [{model}] error {resp.status_code}: {resp.text[:200]}", flush=True)
        return None, False

    except Exception as e:
        print(f"❌ [{model}] exception: {e}", flush=True)
        return None, False


# ══════════════════════════════════════════════════════════════════════════════
# TRIAGE ROUTER  (called only when keyword match fails)
# One small call to llama-3.1-8b-instant:
#   a) decides if DB is needed at all
#   b) if yes, picks the best file key from the full list
# ══════════════════════════════════════════════════════════════════════════════

async def triage(question: str) -> tuple[bool, str | None]:
    """Returns (needs_db, file_key_or_None)."""
    if not LOCAL_FILE_MAP:
        return True, None

    keys = ", ".join(LOCAL_FILE_MAP.keys())
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": f"Available keys: {keys}\nMessage: {question}"},
    ]

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=40)
    if not text:
        return True, None

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        result  = json.loads(cleaned)
        needs   = bool(result.get("needs_db", True))
        key     = result.get("key") or None
        if key and key not in LOCAL_FILE_MAP:
            key = next((k for k in LOCAL_FILE_MAP if k in text), None)
        return needs, key
    except Exception:
        for k in LOCAL_FILE_MAP:
            if k in text:
                return True, k
        return True, None


# ══════════════════════════════════════════════════════════════════════════════
# ANSWER HELPER  ─  rotates through model pool on 429
# ══════════════════════════════════════════════════════════════════════════════

async def get_answer(messages: list) -> str:
    for model in ANSWER_MODELS:
        result, rotate = await groq_chat(messages, model=model, max_tokens=800)
        if result:
            print(f"✅ Answered with [{model}]", flush=True)
            return result
        if not rotate:
            break
    return (
        "Noooo all my backup models are tired too... "
        "Give it a minute and try again? *dramatically collapses in lobby*"
    )


# ══════════════════════════════════════════════════════════════════════════════
# LIGHTWEIGHT PORT KEEP-ALIVE (Render)
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# DISCORD BOT
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"🤖 Hafu Bot online as {bot.user.name} (ID: {bot.user.id})")
    print(f"✨ Answer model pool: {ANSWER_MODELS}")
    print("🌸 Hafu is ready to reluctantly answer questions from the lobby.")

    port = int(os.environ.get("PORT", 10000))
    try:
        server = await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
        asyncio.get_event_loop().create_task(server.serve_forever())
        print(f"🌐 Keep-alive online on port {port}", flush=True)
    except Exception as e:
        print(f"⚠️ Keep-alive failed: {e}", flush=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if bot.user not in message.mentions:
        return

    question = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not question:
        question = "hello"

    if not GROQ_TOKEN:
        await message.reply("Omg my GROQ_TOKEN is missing — did someone forget the env var?! *taps foot*")
        return

    async with message.channel.typing():

        # ── Fast path: obvious casual chat ────────────────────────────────────
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": question},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
            return

        # ── Step 1: Local keyword route (zero API cost) ────────────────────────
        routed_stem = route_local(question)

        if routed_stem:
            print(f"⚡ Local route: '{question[:60]}' ──► [{routed_stem}]", flush=True)
        else:
            # ── Step 2: Triage call (router model, ~40 tokens out) ─────────────
            print(f"🔍 Triage: '{question[:60]}'", flush=True)
            needs_db, routed_stem = await triage(question)

            if not needs_db:
                print("   ──► No DB needed, answering as Hafu", flush=True)
                text_out = await get_answer([
                    {"role": "system", "content": CASUAL_SYSTEM},
                    {"role": "user",   "content": question},
                ])
                await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
                return

            if routed_stem:
                print(f"   ──► [{routed_stem}]", flush=True)
            else:
                routed_stem = "frontpage"
                print("   Fallback ──► [frontpage]", flush=True)

        # ── Step 3: Load context file ──────────────────────────────────────────
        if not LOCAL_FILE_MAP:
            await message.reply("My database isn't loaded. Did the sync not run? *panics quietly*")
            return

        if routed_stem not in LOCAL_FILE_MAP:
            print(f"   ⚠️  [{routed_stem}] not on disk, falling back to frontpage", flush=True)
            routed_stem = "frontpage"

        try:
            with open(LOCAL_FILE_MAP[routed_stem], "r", encoding="utf-8") as f:
                context_data = f.read().strip()
        except Exception as e:
            print(f"❌ File read error: {e}", flush=True)
            await message.reply("Ugh, I went for my notes and the file just vanished. Something's wrong with the file system.")
            return

        # ── Step 4: Generate answer ────────────────────────────────────────────
        text_out = await get_answer([
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user",   "content": f"CONTEXT:\n{context_data}\n\nQuestion: {question}"},
        ])

        await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: Missing DISCORD_TOKEN.")
    elif not GROQ_TOKEN:
        print("❌ Error: Missing GROQ_TOKEN.")
    else:
        bot.run(TOKEN)

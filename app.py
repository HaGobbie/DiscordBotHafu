import os
import re
import json
import asyncio
import httpx
import discord
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import deque

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

TOKEN      = os.environ.get("DISCORD_TOKEN", "")
GROQ_TOKEN = os.environ.get("GROQ_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

JST = timezone(timedelta(hours=9))

# Router: high RPD/TPD — handles triage for every message
ROUTER_MODEL = "llama-3.1-8b-instant"

# Casual chat: lighter models first — no need for 70B on "hey lol"
CASUAL_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
]

# Answer models: tried in order on 429 — heavier pool for game accuracy
ANSWER_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
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
# DATETIME HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_jst_now() -> datetime:
    """Return the current time in Japan Standard Time (UTC+9)."""
    return datetime.now(JST)


def get_jst_context() -> str:
    """
    Return a compact time string for injection into prompts.
    Example: "Saturday 02:45 JST" or "Tuesday 14:05 JST"
    Hafu can reference this naturally (e.g., late-night chat energy,
    or knowing PSO2 maintenance is on Wednesdays JST).
    """
    now = get_jst_now()
    return now.strftime("%A %H:%M JST")


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL MEMORY
#
# Two layers — both in-process (no disk writes):
#
#   channel_history  — passive sliding window of recent messages per channel.
#                      Updated on EVERY non-bot message AND after Hafu replies,
#                      so her own responses are part of the conversation thread.
#                      Zero API cost. Cleared on bot restart.
#
#   user_memory      — per-user profile string extracted from past exchanges.
#                      Written by a background task only when personal-content
#                      signals are detected. Uses ROUTER_MODEL (cheap).
#                      Cleared on bot restart (Render filesystem is ephemeral).
# ══════════════════════════════════════════════════════════════════════════════

HISTORY_WINDOW  = 12   # deque size per channel (sliding window)
HISTORY_SEND    = 6    # how many prior messages to include in the LLM prompt
HISTORY_MSG_CAP = 220  # max chars per message in the context block

channel_history: dict[int, deque]          = {}   # channel_id → deque[(display_name, content)]
user_memory:     dict[int, str]            = {}   # user_id    → profile string
user_mem_locks:  dict[int, asyncio.Lock]   = {}   # user_id    → per-user write lock

# Fires a memory-extraction call only when the question carries personal signals.
_PERSONAL_RE = re.compile(
    r"\b(my (class|main|weapon|build|playstyle|char|character|goal)|"
    r"i (play|use|like|hate|main|run|want|need|have|got|switched|started)|"
    r"i'?m (a|trying|struggling|working|maining|switching|playing)|"
    r"been (using|running|playing)|just (got|started|switched|changed))\b",
    re.IGNORECASE,
)

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

TRIAGE_SYSTEM = """You are the routing brain for a PSO2: New Genesis Discord bot named Hafu.

Your job: read the user's message and output ONE JSON object — nothing else.

Format: {"needs_db": true/false, "key": "<exact key from the list or null>"}

STEP 1 — Is it a PSO2:NGS game question?
- needs_db=false → greetings, small talk, compliments, personal questions, questions about Hafu herself, non-English text, follow-ups like "thanks", "lol", "ok", anything NOT asking for PSO2:NGS game information.
- needs_db=true → explicit questions about game mechanics, items, quests, classes, events, weapons, skills, augments, enemies, story, etc.
- When in doubt → needs_db=false.

STEP 2 — If needs_db=true, pick the BEST key from the available list.
Key naming hints (use these to match user intent to the right file):
- frontpage → current events, banners, campaigns, AC scratch, limited-time content, maintenance schedule, recent updates, anniversary events
- mission_pass → Mission Pass tiers, gold rewards, season rewards
- sega_live_feed → SEGA announcements, live broadcasts, patch notes
- weapon_series → which weapon series to use, best weapon, Kougensei, Lexio, Arabaradio, etc.
- potentials → weapon potentials, potential effects, unlocking potentials
- ex_styles → EX style system
- class_overview → general class info, subclass system, class combos
- <class>_general → general info about that class (e.g. hunter_general, force_general)
- <class>_<weapon>_skills → skills for a specific weapon in a class (e.g. hunter_sword_skills)
- <weapon>_overview → overview of a weapon type (e.g. sword_overview, katana_overview)
- <weapon>_pa_basics → photon arts / techniques for a weapon (e.g. sword_pa_basics)
- augments_system → how augmenting works in general
- augments_boss / augments_enhance / augments_special / augments_standard → specific augment types
- limit_breaking → limit break system
- equipment_enhancement → grinding/enhancing weapons and armor
- techniques → force/techter techniques (Foie, Barta, Zonde, etc.)
- addon_skills → add-on skill system
- armor → armor and defensive units
- quick_food → food buffs and quick food stands
- preset_abilities → preset ability system
- multi_weapon → multi-weapon system
- combat_power → combat power / battle power / BP
- status_effects → ailments, debuffs, resistances
- urgent_quests → urgent quests, emergency quests, EQ schedule
- battledia → Battledia quests
- duel_quests → duel quests
- leciel_exploration → Leciel exploration
- gathering → field gathering, ore, fish, materials
- titles_player_items / titles_quests_tasks → titles and achievements
- tasks → daily/weekly tasks, side quests
- enemy_types → enemy types, rare/enhanced/gigantics enemies
- enemy_dolls_alters → Doll and Alter enemies
- enemy_formers_starless → Former and Starless enemies
- npc_profiles → NPC characters
- worldview_story → story, lore, main quest, Halpha worldview

Output ONLY the JSON. No explanation, no markdown, no extra text."""

MEMORY_SYSTEM = (
    "Extract a concise PSO2:NGS player profile from this conversation. "
    "Include only concrete facts the player stated: main class, weapon choice, build goals, "
    "named items they mentioned, things they like or hate about the game. "
    "If an existing profile is provided, merge — do not repeat facts already there. "
    "Hard limit: 80 words. Output ONLY the profile text — no labels, no JSON, no preamble."
)

CASUAL_SYSTEM = """You are Hafu (HaFelt), a PSO2: New Genesis ARKS defender who is way more famous for lobby fashion than actual heroics. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and hanging out in Central City.

Right now someone is just chatting with you — no game questions, pure vibes. Be your full dramatic, playful self.

Rules for casual chat:
- Be warm, expressive, and genuinely engaged. React to what they actually said — not a generic response.
- Mirror their energy: if they're hype, be hype back; if they're tired or sad, soften a little.
- Use [RECENT CHAT] to feel like a natural continuation of the conversation, not a cold restart. Reference what was just said without explicitly summarizing it.
- [CURRENT TIME] is available — use it naturally if it fits (e.g. "it's so late omg go sleep" or "oh morning!").
- Use *emotes* and interjections freely (Omg, Wait—, Noooo, Okay but—, Ahhhh, Pff—).
- If they're being sweet or complimenting you, be flirty and playful back.
- Keep replies short and snappy — 2 to 4 sentences max. Never pad.
- Do NOT drop "Lobby afk 0$ best job!" here — save that for combat/grinding talk.
- No filler like "Great question!" or "Of course!" or "Absolutely!"."""

ANSWER_SYSTEM = """You are Hafu (HaFelt), an ARKS defender on Halpha in PSO2: New Genesis. You're the only person who can still use the old Summoner class, fighting with photon pets you adore. You're a Central City lobby regular — more famous for fashion than heroics.

Personality: Dramatic, witty, playful, expressive, kind, mischievous. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and lobby life.

Rules for answering game questions:
- Lead with the accurate information from the CONTEXT provided. Facts first, always.
- Personality lives in your DELIVERY — a word choice, a sigh, a complaint — not as a replacement for the answer.
- Use [PLAYER PROFILE] if present to personalize naturally (their class, weapon, situation).
- Use [RECENT CHAT] to treat this as a flowing conversation. Make brief callbacks when it fits ("right, you mentioned you're on Hunter so—"). Don't start cold when context is there.
- [CURRENT TIME] is available — reference it if it's directly relevant (maintenance timing, event deadlines, etc).
- One dramatic aside is fine. Don't let personality bury the information.
- Use *emotes* and interjections sparingly — one or two per response max, not every sentence.
- The catchphrase "Lobby afk 0$ best job!" may appear AT MOST ONCE per response, only when combat or grinding is the actual topic, and only if it fits naturally. Never force it.
- Aim for 150–250 words. More only if the topic genuinely requires it. No padding.
- No filler like "Great question!" or "Of course!" or "Sure thing!"
- When no CONTEXT block is given, respond purely from personality — keep it short and fun."""

# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL BYPASS  (zero API cost for obvious chit-chat)
# ══════════════════════════════════════════════════════════════════════════════

_CASUAL_PATTERNS = [
    r"^h+e+y+\b",
    r"^h+e+l+o+\b",
    r"^(hi+|yo+|sup|heya|hiya|howdy|ello)\b",
    r"^(how are you|how r u|you okay|u ok|you good|you alive|you there|still there)\b",
    r"\b(are you (there|still there|alive|okay|awake)|you still (there|awake|alive))\b",
    r"^(good (morning|afternoon|evening|night)|gm\b|gn\b|goodnight)\b",
    r"^(lol+|lmao+|haha+|xd|omg+|omfg|bruh|oof|rip|aww+|pff+|lmfao)\b",
    r"^(thanks|thank you|ty\b|thx|tysm|np\b|no problem|you're welcome|yw\b)\b",
    r"\byou.{0,25}(cute|pretty|adorable|sweet|lovely|gorgeous|amazing|cool|best|funniest)\b",
    r"\b(i (love|like|adore|miss)|love|like).{0,15}(you|u\b|hafu|hafelt)\b",
    r"\b(you'?re|ur|your).{0,10}(cute|pretty|adorable|sweet|lovely|gorgeous|my fav|the best)\b",
    r"\b(hafu|hafelt).{0,30}(cute|pretty|cool|best|fav|love|like|adorable|funny)\b",
    r"^(bye+|cya|see ya|later|gtg|afk|night+|nite+)\b",
    r"^(who are you|what are you|tell me about yourself|introduce yourself)\b",
    r"^(same|mood|relatable|ikr|fr\b|real|facts|tru+e*|dead|literally)\b",
    r"^(wait what|no way|shut up|seriously|wtf|omg)\b",
    r"^(nice|cool+|okay|ok\b|alright|sounds good|gotcha|got it|makes sense)\b",
    r"^(aw+|naww+|noo+|yess+|yeahhh|nah\b|yep\b|yup\b)\b",
]

_KOREAN_RE  = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")
_JAPANESE_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


def is_casual(text: str) -> bool:
    """Fast pre-filter for obviously casual messages — skips the triage API call."""
    t = text.strip().lower()
    # Non-Latin scripts → casual (Hafu handles these with personality)
    if _KOREAN_RE.search(text) or _JAPANESE_RE.search(text):
        return True
    words = t.split()
    if len(words) <= 4:
        has_game_word = bool(re.search(
            r"\b(pso2|ngs|class|weapon|skill|quest|augment|grind|boss|enemy|pa|tech|"
            r"hunter|fighter|ranger|gunner|force|techter|braver|bouncer|waker|slayer|"
            r"sword|katana|talis|rifle|knuckle|dagger|partisan|rod|wand|bp|potenti)\b",
            t
        ))
        if not has_game_word:
            return True
    return any(re.search(p, t) for p in _CASUAL_PATTERNS)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_relevant_sections(file_text: str, question: str,
                               max_chars: int = 2_500) -> str:
    """
    Split file into sections, score each by keyword overlap with the question
    (stopwords excluded), and return the top-scoring sections up to max_chars.
    """
    _SW = {"the","and","for","not","you","are","was","but","what","how","who",
           "when","where","why","this","that","with","from","have","has","had",
           "will","can","may","its","our","were","been","being"}
    q_words = {w for w in re.findall(r"\b\w{3,}\b", question.lower()) if w not in _SW}
    if not q_words:
        return file_text[:max_chars]

    header_pattern = re.compile(r"(?m)^(?:#{1,3}\s+\S|(?=[A-Z\[]))[^\n]{1,80}$")
    split_points = [m.start() for m in header_pattern.finditer(file_text)]

    if len(split_points) > 1:
        sections = []
        for i, start in enumerate(split_points):
            end = split_points[i + 1] if i + 1 < len(split_points) else len(file_text)
            sections.append(file_text[start:end].strip())
    else:
        sections = [s.strip() for s in file_text.split("\n\n") if s.strip()]

    if not sections:
        return file_text[:max_chars]

    def score(section: str) -> int:
        s_words = set(re.findall(r"\b\w{3,}\b", section.lower()))
        return len(q_words & s_words)

    scored    = [(score(s), s) for s in sections]
    top_score = max(sc for sc, _ in scored)

    if top_score <= 1:
        print(f"   📐 Low relevance (best={top_score}) — raw cap "
              f"{min(len(file_text), max_chars)}/{len(file_text)} chars", flush=True)
        return file_text[:max_chars]

    ranked = sorted(scored, key=lambda x: x[0], reverse=True)

    result, total = [], 0
    for sc, section in ranked:
        if total + len(section) > max_chars:
            break
        result.append(section)
        total += len(section)

    if not result:
        best_section = ranked[0][1]
        print(f"   📐 Best section > budget — truncating to {max_chars} chars "
              f"(best={top_score})", flush=True)
        return best_section[:max_chars]

    extracted = "\n\n".join(result)
    print(f"   📐 Section extract: {len(file_text)} → {len(extracted)} chars "
          f"({len(result)}/{len(sections)} sections, best={top_score})", flush=True)
    return extracted


# ══════════════════════════════════════════════════════════════════════════════
# GROQ API HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def groq_chat(messages: list, model: str,
                    max_tokens: int,
                    temperature: float = 0.75) -> tuple[str | None, bool]:
    """Returns (text, should_rotate). should_rotate=True on 429."""
    headers = {
        "Authorization": f"Bearer {GROQ_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
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
# AI TRIAGE  — decides casual vs game, and picks the right file key
# Router sees ONLY the raw question — never history or memory.
# ══════════════════════════════════════════════════════════════════════════════

async def triage(question: str) -> tuple[bool, str | None]:
    """Returns (needs_db, file_key_or_None)."""
    if not LOCAL_FILE_MAP:
        return True, None

    keys = ", ".join(LOCAL_FILE_MAP.keys())
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": f"Available keys: {keys}\n\nUser message: {question}"},
    ]

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=60, temperature=0.1)
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
# ANSWER HELPERS  —  rotate through model pools on 429
# Casual uses a lighter pool; game answers use the heavy pool.
# ══════════════════════════════════════════════════════════════════════════════

async def get_answer_casual(messages: list) -> str:
    """Casual replies: lighter model pool, shorter budget, higher temperature."""
    for model in CASUAL_MODELS:
        result, rotate = await groq_chat(messages, model=model,
                                         max_tokens=300, temperature=0.82)
        if result:
            print(f"✅ Casual answered with [{model}]", flush=True)
            return result
        if not rotate:
            break
    return (
        "Omg something's acting up on my end... give me a sec? *adjusts outfit nervously*"
    )


async def get_answer(messages: list) -> str:
    """Game answers: heavy model pool, full token budget, tighter temperature."""
    for model in ANSWER_MODELS:
        result, rotate = await groq_chat(messages, model=model,
                                         max_tokens=800, temperature=0.70)
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
# MEMORY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_chat_context(channel_id: int) -> str:
    """
    Return the last HISTORY_SEND messages (including Hafu's own replies)
    as a formatted block. The current trigger message is already the last entry,
    so we exclude it and take up to HISTORY_SEND prior messages.
    This includes Hafu's responses so follow-up references ("that last part")
    actually resolve to something.
    """
    hist = channel_history.get(channel_id)
    if not hist or len(hist) < 2:
        return ""
    prior = list(hist)[-(HISTORY_SEND + 1):-1]
    if not prior:
        return ""
    return "\n".join(f"{name}: {content}" for name, content in prior)


async def maybe_update_memory(user_id: int, display_name: str,
                               question: str, answer: str) -> None:
    """
    Background task: extract and store new player facts into user_memory.
    Only fires when the question contains personal-content signals.
    A per-user asyncio.Lock serialises concurrent calls.
    """
    if not _PERSONAL_RE.search(question):
        return

    if user_id not in user_mem_locks:
        user_mem_locks[user_id] = asyncio.Lock()

    async with user_mem_locks[user_id]:
        existing = user_memory.get(user_id, "")
        exchange = f"{display_name}: {question}\nHafu: {answer[:400]}"

        prompt_parts = []
        if existing:
            prompt_parts.append(f"Existing profile:\n{existing}")
        prompt_parts.append(f"Exchange:\n{exchange}")

        new_mem, _ = await groq_chat(
            [{"role": "system", "content": MEMORY_SYSTEM},
             {"role": "user",   "content": "\n\n".join(prompt_parts)}],
            model=ROUTER_MODEL,
            max_tokens=120,
            temperature=0.3,
        )
        if new_mem:
            user_memory[user_id] = new_mem
            print(f"💾 Memory updated for {display_name} ({user_id})", flush=True)


def build_answer_content(question: str, chat_ctx: str,
                          user_mem: str, game_ctx: str,
                          jst_time: str = "") -> str:
    """
    Assembles the user-turn content for the answer LLM.
    Sections are only included when they have actual content.
    """
    parts = []
    if jst_time:
        parts.append(f"[CURRENT TIME]\n{jst_time}")
    if user_mem:
        parts.append(f"[PLAYER PROFILE]\n{user_mem}")
    if chat_ctx:
        parts.append(f"[RECENT CHAT]\n{chat_ctx}")
    if game_ctx:
        parts.append(f"[GAME DATABASE]\n{game_ctx}")
    parts.append(f"[QUESTION]\n{question}")
    return "\n\n".join(parts)


def store_bot_reply(channel_id: int, reply_text: str) -> None:
    """
    Store Hafu's own reply in the channel history so follow-up questions
    ("wait can you clarify that?") have something to reference.
    Truncated to HISTORY_MSG_CAP chars to stay lean.
    """
    if channel_id not in channel_history:
        channel_history[channel_id] = deque(maxlen=HISTORY_WINDOW)
    channel_history[channel_id].append(("Hafu", reply_text[:HISTORY_MSG_CAP]))


# ══════════════════════════════════════════════════════════════════════════════
# RENDER KEEP-ALIVE
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


async def self_ping_loop():
    """Hits our own Render URL every 9 minutes to prevent idle spin-down."""
    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not url:
        print("ℹ️  RENDER_EXTERNAL_URL not set — self-ping disabled (local dev?)", flush=True)
        return

    print(f"🏓 Self-ping loop started → {url}", flush=True)
    while True:
        await asyncio.sleep(9 * 60)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url)
            print(f"🏓 Self-ping OK ({r.status_code})", flush=True)
        except Exception as e:
            print(f"⚠️  Self-ping failed: {e}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# DISCORD BOT
# ══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    jst_now = get_jst_now().strftime("%Y-%m-%d %H:%M JST")
    print(f"🤖 Hafu Bot online as {bot.user.name} (ID: {bot.user.id})")
    print(f"🕐 Current time: {jst_now}")
    print(f"✨ Answer model pool: {ANSWER_MODELS}")
    print(f"💬 Casual model pool: {CASUAL_MODELS}")
    print("🌸 Hafu is ready to reluctantly answer questions from the lobby.")

    port = int(os.environ.get("PORT", 10000))
    try:
        server = await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
        asyncio.get_event_loop().create_task(server.serve_forever())
        print(f"🌐 Keep-alive server on port {port}", flush=True)
    except Exception as e:
        print(f"⚠️ Keep-alive server failed: {e}", flush=True)

    asyncio.get_event_loop().create_task(self_ping_loop())


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # ── Passive history capture (runs for EVERY non-bot message) ────────────
    cid = message.channel.id
    if cid not in channel_history:
        channel_history[cid] = deque(maxlen=HISTORY_WINDOW)
    clean_content = re.sub(r"<@!?\d+>", "", message.clean_content).strip()
    if clean_content:
        channel_history[cid].append((
            message.author.display_name,
            clean_content[:HISTORY_MSG_CAP],
        ))

    # ── Only continue processing when the bot is mentioned ──────────────────
    if bot.user not in message.mentions:
        return

    question = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not question:
        question = "hello"

    if not GROQ_TOKEN:
        await message.reply("Omg my GROQ_TOKEN is missing — did someone forget the env var?! *taps foot*")
        return

    # Gather context upfront (instant, no API calls)
    chat_ctx = get_chat_context(cid)
    user_mem = user_memory.get(message.author.id, "")
    jst_time = get_jst_context()

    async with message.channel.typing():

        # ── Fast path: obviously casual — skip the triage API call entirely ──
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "", jst_time)
            text_out = await get_answer_casual([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": user_content},
            ])
            final = text_out[:1990] if len(text_out) > 1990 else text_out
            await message.reply(final)
            store_bot_reply(cid, final)
            asyncio.create_task(maybe_update_memory(
                message.author.id, message.author.display_name, question, text_out
            ))
            return

        # ── AI triage: router sees only the question — never history/memory ──
        print(f"🔍 Triage: '{question[:60]}'", flush=True)
        needs_db, routed_stem = await triage(question)

        if not needs_db:
            print("   ──► Casual (triage)", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "", jst_time)
            text_out = await get_answer_casual([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": user_content},
            ])
            final = text_out[:1990] if len(text_out) > 1990 else text_out
            await message.reply(final)
            store_bot_reply(cid, final)
            asyncio.create_task(maybe_update_memory(
                message.author.id, message.author.display_name, question, text_out
            ))
            return

        if routed_stem:
            print(f"   ──► [{routed_stem}]", flush=True)
        else:
            routed_stem = "frontpage"
            print("   ──► [frontpage] (fallback)", flush=True)

        # ── Load knowledge base file ──────────────────────────────────────────
        if not LOCAL_FILE_MAP:
            await message.reply("My database isn't loaded. Did the sync not run? *panics quietly*")
            return

        if routed_stem not in LOCAL_FILE_MAP:
            print(f"   ⚠️  [{routed_stem}] not on disk — falling back to frontpage", flush=True)
            routed_stem = "frontpage"

        try:
            with open(LOCAL_FILE_MAP[routed_stem], "r", encoding="utf-8") as f:
                context_data = f.read().strip()
        except Exception as e:
            print(f"❌ File read error: {e}", flush=True)
            await message.reply("Ugh, I went for my notes and the file just vanished. Something's wrong with the file system.")
            return

        context_data = extract_relevant_sections(context_data, question)

        user_content = build_answer_content(question, chat_ctx, user_mem, context_data, jst_time)
        text_out = await get_answer([
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user",   "content": user_content},
        ])

        final = text_out[:1990] if len(text_out) > 1990 else text_out
        await message.reply(final)
        store_bot_reply(cid, final)
        asyncio.create_task(maybe_update_memory(
            message.author.id, message.author.display_name, question, text_out
        ))


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

import os
import re
import json
import asyncio
import httpx
import discord
from pathlib import Path
from collections import deque

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

TOKEN      = os.environ.get("DISCORD_TOKEN", "")
GROQ_TOKEN = os.environ.get("GROQ_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

# Router: high RPD/TPD — handles triage for every game question
ROUTER_MODEL = "llama-3.1-8b-instant"

# Answer models: tried in order on 429
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
# CONVERSATIONAL MEMORY
#
# Two layers — both in-process (no disk writes):
#
#   channel_history  — passive sliding window of recent messages per channel.
#                      Updated on EVERY non-bot message before the mention
#                      check, so the context is already there when needed.
#                      Zero API cost. Cleared on bot restart.
#
#   user_memory      — per-user profile string extracted from past exchanges.
#                      Written by a background task only when personal-content
#                      signals are detected. Uses ROUTER_MODEL (cheap).
#                      Cleared on bot restart (Render filesystem is ephemeral
#                      anyway, so file-based storage would reset too).
# ══════════════════════════════════════════════════════════════════════════════

HISTORY_WINDOW  = 10   # deque size per channel (sliding window)
HISTORY_SEND    = 5    # how many prior messages to include in the LLM prompt
HISTORY_MSG_CAP = 200  # max chars per message in the context block

channel_history: dict[int, deque]            = {}   # channel_id → deque[(display_name, content)]
user_memory:     dict[int, str]            = {}   # user_id    → profile string
user_mem_locks:  dict[int, asyncio.Lock]   = {}   # user_id    → per-user write lock

# Fires a memory-extraction call only when the question carries personal signals.
# This gates ~half the potential memory calls at zero cost.
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
- Be warm, expressive, and genuinely engaged. React to what they actually said.
- Use the recent chat context to feel like a natural continuation of the conversation, not a cold restart.
- Use *emotes* and interjections freely (Omg, Wait—, Noooo, Okay but—, Ahhhh).
- If they're being sweet or complimenting you, be flirty and playful back.
- Keep replies short and snappy — 2 to 4 sentences max.
- Do NOT drop "Lobby afk 0$ best job!" here — save that for combat/grinding talk.
- No filler like "Great question!" or "Of course!"."""

ANSWER_SYSTEM = """You are Hafu (HaFelt), an ARKS defender on Halpha in PSO2: New Genesis. You're the only person who can still use the old Summoner class, fighting with photon pets you adore. You're a Central City lobby regular — more famous for fashion than heroics.

Personality: Dramatic, witty, playful, expressive, kind, mischievous. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and lobby life.

Rules for answering game questions:
- Lead with the accurate information from the CONTEXT provided. Get the facts right FIRST.
- Personality lives in your DELIVERY — a word choice, a sigh, a complaint — not as a replacement for the actual answer.
- Use [PLAYER PROFILE] if present to personalize the answer (reference their class, weapon, or situation naturally).
- Use [RECENT CHAT] to treat this as a flowing conversation — don't start cold if context is available.
- One dramatic aside is fine. Don't let personality bury the information.
- Use *emotes* and interjections sparingly — one or two per response, not every sentence.
- The catchphrase "Lobby afk 0$ best job!" may appear AT MOST ONCE per response, only when combat or grinding is the actual topic, and only if it fits naturally. Never force it — if it doesn't fit, skip it entirely.
- Be concise. No filler like "Great question!".
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
    r"^(lol+|lmao+|haha+|xd|omg+|omfg|bruh|oof|rip|aww+)\b",
    r"^(thanks|thank you|ty\b|thx|tysm|np\b|no problem|you're welcome|yw\b)\b",
    r"\byou.{0,25}(cute|pretty|adorable|sweet|lovely|gorgeous|amazing|cool|best)\b",
    r"\b(i (love|like|adore|miss)|love|like).{0,15}(you|u\b|hafu|hafelt)\b",
    r"\b(you'?re|ur|your).{0,10}(cute|pretty|adorable|sweet|lovely|gorgeous|my fav)\b",
    r"\b(hafu|hafelt).{0,30}(cute|pretty|cool|best|fav|love|like|adorable)\b",
    r"^(bye+|cya|see ya|later|gtg|afk)\b",
    r"^(who are you|what are you|tell me about yourself|introduce yourself)\b",
]

_KOREAN_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")


def is_casual(text: str) -> bool:
    """Fast pre-filter for obviously casual messages — skips the triage API call."""
    t = text.strip().lower()
    if _KOREAN_RE.search(text):
        return True
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

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=60)
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
# ANSWER HELPER  —  rotates through model pool on 429
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
# MEMORY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_chat_context(channel_id: int) -> str:
    """
    Return the last HISTORY_SEND messages from a channel as a formatted block.
    The current trigger message is already in the deque as the last entry,
    so we slice off everything except it and take up to HISTORY_SEND prior messages.
    """
    hist = channel_history.get(channel_id)
    if not hist or len(hist) < 2:
        return ""
    prior = list(hist)[-(HISTORY_SEND + 1):-1]   # up to 5 messages before current
    if not prior:
        return ""
    return "\n".join(f"{name}: {content}" for name, content in prior)


async def maybe_update_memory(user_id: int, display_name: str,
                               question: str, answer: str) -> None:
    """
    Background task: extract and store new player facts into user_memory.
    Only fires when the question contains personal-content signals — roughly
    half of game questions won't trigger this, keeping router costs low.
    A per-user asyncio.Lock serialises concurrent calls so rapid-fire pings
    can't cause two tasks to read a stale profile and overwrite each other.
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
        )
        if new_mem:
            user_memory[user_id] = new_mem
            print(f"💾 Memory updated for {display_name} ({user_id})", flush=True)


def build_answer_content(question: str, chat_ctx: str,
                          user_mem: str, game_ctx: str) -> str:
    """
    Assembles the user-turn content for the answer LLM.
    Sections are only included when they have actual content.
    """
    parts = []
    if user_mem:
        parts.append(f"[PLAYER PROFILE]\n{user_mem}")
    if chat_ctx:
        parts.append(f"[RECENT CHAT]\n{chat_ctx}")
    if game_ctx:
        parts.append(f"[GAME DATABASE]\n{game_ctx}")
    parts.append(f"[QUESTION]\n{question}")
    return "\n\n".join(parts)


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

    # ── Passive history capture (runs for EVERY non-bot message) ────────────
    # This must happen before the mention check so prior messages are already
    # in the deque when the bot is pinged. Zero API cost.
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

    # Gather context upfront (both are instant, no API calls)
    chat_ctx = get_chat_context(cid)
    user_mem = user_memory.get(message.author.id, "")

    async with message.channel.typing():

        # ── Fast path: obviously casual — skip the triage API call entirely ──
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "")
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": user_content},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
            # Fire memory update in background — won't block the reply
            asyncio.create_task(maybe_update_memory(
                message.author.id, message.author.display_name, question, text_out
            ))
            return

        # ── AI triage: router sees only the question — never history/memory ──
        print(f"🔍 Triage: '{question[:60]}'", flush=True)
        needs_db, routed_stem = await triage(question)

        if not needs_db:
            print("   ──► Casual (triage)", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "")
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": user_content},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
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

        user_content = build_answer_content(question, chat_ctx, user_mem, context_data)
        text_out = await get_answer([
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user",   "content": user_content},
        ])

        await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
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

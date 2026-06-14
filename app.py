import os
import re
import json
import asyncio
import httpx
import discord
import chromadb
from chromadb.utils import embedding_functions
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

# Router: binary triage only — high RPD model, tiny output, cheap
ROUTER_MODEL = "llama-3.1-8b-instant"

# Casual chat: lighter models first
CASUAL_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
]

# Answer models: heavy pool for game accuracy
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
# CHROMADB  —  in-memory, ephemeral (clears on restart)
#
#   guide_collection   — knowledge_base/*.txt files, split into ~600-char chunks.
#                        Semantic search finds relevant passages per question.
#
#   profile_collection — one doc per user, upserted on every memory update.
#                        Metadata is kept plain/uncompressed for native filtering.
# ══════════════════════════════════════════════════════════════════════════════

_ef           = embedding_functions.DefaultEmbeddingFunction()
chroma_client = chromadb.EphemeralClient()

guide_collection = chroma_client.get_or_create_collection(
    name="guides",
    embedding_function=_ef,
)
profile_collection = chroma_client.get_or_create_collection(
    name="user_profiles",
    embedding_function=_ef,
)

KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
_CHUNK_SIZE = 600


def _split_into_chunks(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    """
    Split text into paragraph-aware chunks with one-paragraph overlap.
    Overlap keeps context continuous across chunk boundaries.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > size and current:
            chunks.append("\n\n".join(current))
            current = [current[-1], para]
            current_len = sum(len(c) for c in current)
        else:
            current.append(para)
            current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))

    return chunks or [text[:size]]


def load_knowledge_base_into_chroma() -> int:
    """
    Index all knowledge_base/*.txt files into guide_collection on startup.
    Returns the total number of chunks stored.
    Text is stored raw — embeddings require uncompressed content.
    """
    if not KNOWLEDGE_BASE_DIR.exists():
        print("⚠️  'knowledge_base/' not found — guide search disabled.", flush=True)
        return 0

    total = 0
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        stem = txt_file.stem
        try:
            text = txt_file.read_text(encoding="utf-8").strip()
        except Exception as e:
            print(f"⚠️  Could not read {txt_file}: {e}", flush=True)
            continue

        chunks    = _split_into_chunks(text)
        ids       = [f"{stem}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": stem, "chunk": i} for i in range(len(chunks))]

        try:
            guide_collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
            total += len(chunks)
        except Exception as e:
            print(f"⚠️  ChromaDB upsert failed for {stem}: {e}", flush=True)

    return total


def _search_guides_sync(query: str, n_results: int = 4) -> str:
    """Synchronous inner — always call via search_guides() from async code."""
    try:
        results = guide_collection.query(
            query_texts=[query],
            n_results=n_results,
        )
        docs = results.get("documents", [[]])[0]
        return "\n\n---\n\n".join(docs) if docs else ""
    except Exception as e:
        print(f"⚠️  Guide search error: {e}", flush=True)
        return ""


async def search_guides(query: str, n_results: int = 4) -> str:
    """
    Async wrapper: runs ONNX embedding in a thread pool so the Discord
    heartbeat is never blocked by CPU-bound inference work.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_guides_sync, query, n_results)


# ══════════════════════════════════════════════════════════════════════════════
# USER PROFILE  —  ChromaDB upsert (one record per user, always overwritten)
# ══════════════════════════════════════════════════════════════════════════════

def get_user_profile(user_id: int) -> str:
    """Fetch the stored fact-profile for a user. Returns '' if none exists."""
    try:
        result = profile_collection.get(ids=[f"profile_{user_id}"])
        docs = result.get("documents", [])
        return docs[0] if docs else ""
    except Exception:
        return ""


def _upsert_user_profile_sync(user_id: int, profile_text: str,
                               current_class: str = "") -> None:
    """Synchronous inner — always call via upsert_user_profile() from async code."""
    try:
        profile_collection.upsert(
            ids=[f"profile_{user_id}"],
            documents=[profile_text],
            metadatas=[{
                "user_id":       str(user_id),
                "current_class": current_class,
                "record_type":   "profile",
            }],
        )
    except Exception as e:
        print(f"⚠️  Profile upsert failed for {user_id}: {e}", flush=True)


async def upsert_user_profile(user_id: int, profile_text: str,
                               current_class: str = "") -> None:
    """
    Async wrapper: profile upsert embeds the text via ONNX — must run in
    a thread pool to avoid blocking the Discord heartbeat.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _upsert_user_profile_sync, user_id, profile_text, current_class
    )


# ══════════════════════════════════════════════════════════════════════════════
# DATETIME HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_jst_now() -> datetime:
    return datetime.now(JST)


def get_jst_context() -> str:
    """
    Returns day, time, and date in JST.
    e.g. "Saturday 02:45 JST (2025-06-14)"
    Useful for maintenance window awareness and event deadline checks.
    """
    now = get_jst_now()
    return now.strftime("%A %H:%M JST (%Y-%m-%d)")


def build_system_with_time(base_system: str) -> str:
    """
    Appends current JST time as a quiet background note to the system prompt.
    The model has the context available but is NOT prompted to reference it
    on every reply — only when it genuinely fits.
    """
    return f"{base_system}\n\n[Background: current time is {get_jst_context()}]"


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL MEMORY  —  sliding window per channel
# ══════════════════════════════════════════════════════════════════════════════

HISTORY_WINDOW  = 12
HISTORY_SEND    = 6
HISTORY_MSG_CAP = 220

channel_history: dict[int, deque]        = {}
user_mem_locks:  dict[int, asyncio.Lock] = {}

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

# Change #5: stripped the entire file-key list out of the triage prompt.
# The router now has ONE job: decide needs_game true/false.
# Max output is 20 tokens. Saves ~80% of triage token cost.
TRIAGE_SYSTEM = """You are the routing brain for a PSO2: New Genesis Discord bot named Hafu.

Your job: read the user's message and output ONE JSON object — nothing else.

Format: {"needs_game": true/false}

Rules:
- needs_game=false → greetings, small talk, compliments, personal questions, questions about Hafu herself, non-English text, follow-ups like "thanks", "lol", "ok", anything NOT asking for PSO2:NGS game information.
- needs_game=true → explicit questions about game mechanics, items, quests, classes, events, weapons, skills, augments, enemies, story, etc.
- When in doubt → needs_game=false.

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
- You know the current time — mention it only when it genuinely fits the moment, not as a habit.
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
- You know the current time — bring it up only when it's directly relevant (maintenance windows, event deadlines).
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

_KOREAN_RE   = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")
_JAPANESE_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


def is_casual(text: str) -> bool:
    """Fast pre-filter for obviously casual messages — skips the triage API call."""
    t = text.strip().lower()
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
        "model":       model,
        "messages":    messages,
        "max_tokens":  max_tokens,
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
# TRIAGE  —  binary only, no key routing
# Change #5: 20-token max output, ~80% cheaper than the key-list version.
# ══════════════════════════════════════════════════════════════════════════════

async def triage(question: str) -> bool:
    """Returns True if the question needs game knowledge."""
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": question},
    ]
    text, _ = await groq_chat(messages, model=ROUTER_MODEL,
                               max_tokens=20, temperature=0.1)
    if not text:
        return True

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        result  = json.loads(cleaned)
        return bool(result.get("needs_game", True))
    except Exception:
        return True


# ══════════════════════════════════════════════════════════════════════════════
# ANSWER HELPERS  —  rotate through model pools on 429
# Change #7: casual pool stays lightweight; answer pool reserved for game Qs.
# ══════════════════════════════════════════════════════════════════════════════

async def get_answer_casual(messages: list) -> str:
    for model in CASUAL_MODELS:
        result, rotate = await groq_chat(messages, model=model,
                                         max_tokens=300, temperature=0.82)
        if result:
            print(f"✅ Casual answered with [{model}]", flush=True)
            return result
        if not rotate:
            break
    return "Omg something's acting up on my end... give me a sec? *adjusts outfit nervously*"


async def get_answer(messages: list) -> str:
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
    """Return the last HISTORY_SEND messages as a formatted block."""
    hist = channel_history.get(channel_id)
    if not hist or len(hist) < 2:
        return ""
    prior = list(hist)[-(HISTORY_SEND + 1):-1]
    return "\n".join(f"{name}: {content}" for name, content in prior) if prior else ""


async def maybe_update_memory(user_id: int, display_name: str,
                               question: str, answer: str) -> None:
    """
    Background task: extract player facts from the exchange and upsert into
    ChromaDB profile_collection. Only fires on personal-content signals.
    Change #4: single upsert record per user — no contradictory history buildup.
    """
    if not _PERSONAL_RE.search(question):
        return

    if user_id not in user_mem_locks:
        user_mem_locks[user_id] = asyncio.Lock()

    async with user_mem_locks[user_id]:
        existing = get_user_profile(user_id)
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
            class_match = re.search(
                r"\b(hunter|fighter|ranger|gunner|force|techter|braver|bouncer|waker|slayer)\b",
                new_mem, re.IGNORECASE,
            )
            detected_class = class_match.group(1).title() if class_match else ""
            upsert_user_profile(user_id, new_mem, current_class=detected_class)
            print(f"💾 Profile updated for {display_name} ({user_id})", flush=True)


def build_answer_content(question: str, chat_ctx: str,
                          user_mem: str, game_ctx: str) -> str:
    """
    Assembles the user-turn content for the answer LLM.
    Sections are only included when they have actual content.
    Time context lives quietly in the system prompt — not here.
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


def store_bot_reply(channel_id: int, reply_text: str) -> None:
    """Store Hafu's reply in channel history so follow-ups resolve correctly."""
    if channel_id not in channel_history:
        channel_history[channel_id] = deque(maxlen=HISTORY_WINDOW)
    channel_history[channel_id].append(("Hafu", reply_text[:HISTORY_MSG_CAP]))


# ══════════════════════════════════════════════════════════════════════════════
# PATCH NOTES SCRAPER  (change #8)
#
# Background task that re-indexes key live pages from the PSO2 wiki every
# 4 hours. Keeps Hafu current on events, maintenance, and patch notes without
# manual knowledge_base rebuilds.
# ══════════════════════════════════════════════════════════════════════════════

WIKI_API   = "https://pso2na.arks-visiphone.com/api.php"
LIVE_PAGES = [
    "Portal:New_Genesis",
    "Portal:New_Genesis/Updates",
    "Portal:New_Genesis/Fresh_Finds_Shop",
]


async def _fetch_wiki_wikitext(page_title: str) -> str | None:
    """Fetch and lightly clean wikitext for a given page title."""
    params = (
        f"action=parse&page={page_title.replace(' ', '_')}"
        f"&prop=wikitext&format=json"
    )
    url = f"{WIKI_API}?{params}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url, headers={"User-Agent": "HafuBotNGS/13.0"}
            )
        if resp.status_code != 200:
            return None
        wikitext = (
            resp.json()
            .get("parse", {})
            .get("wikitext", {})
            .get("*", "")
        )
        if not wikitext:
            return None
        # Basic wikitext → plain text stripping
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", wikitext)
        text = re.sub(r"\{\{[^}]+\}\}", "", text)
        text = re.sub(r"={2,}(.+?)={2,}", r"\1", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or None
    except Exception as e:
        print(f"⚠️  Wiki fetch failed for '{page_title}': {e}", flush=True)
        return None


async def patch_scraper_loop():
    """
    Runs every 4 hours. Re-indexes live PSO2 wiki pages so Hafu stays current
    on events, maintenance windows, and patch notes without manual rebuilds.
    """
    await asyncio.sleep(60)  # let the bot fully start first
    print("📡 Patch scraper started.", flush=True)
    while True:
        for page_title in LIVE_PAGES:
            text = await _fetch_wiki_wikitext(page_title)
            if not text:
                continue
            stem      = re.sub(r"[:/\s]+", "_", page_title).lower()
            chunks    = _split_into_chunks(text)
            ids       = [f"live_{stem}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": stem, "chunk": i, "live": "true"} for i in range(len(chunks))]
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda i=ids, c=chunks, m=metadatas:
                        guide_collection.upsert(ids=i, documents=c, metadatas=m)
                )
                print(f"📡 Refreshed '{page_title}' → {len(chunks)} chunks", flush=True)
            except Exception as e:
                print(f"⚠️  Patch scraper upsert failed for '{page_title}': {e}", flush=True)

        await asyncio.sleep(4 * 60 * 60)


# ══════════════════════════════════════════════════════════════════════════════
# RENDER KEEP-ALIVE
# ══════════════════════════════════════════════════════════════════════════════

async def handle_render_ping(reader, writer):
    try:
        await reader.read(256)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
            b"Content-Type: text/plain\r\n\r\nOK"
        )
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
    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not url:
        print("ℹ️  RENDER_EXTERNAL_URL not set — self-ping disabled.", flush=True)
        return
    print(f"🏓 Self-ping loop → {url}", flush=True)
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

    print("📦 Loading knowledge base into ChromaDB (background thread)...", flush=True)
    loop = asyncio.get_event_loop()
    total = await loop.run_in_executor(None, load_knowledge_base_into_chroma)
    print(f"📦 Indexed {total} guide chunks.", flush=True)

    port = int(os.environ.get("PORT", 10000))
    try:
        server = await asyncio.start_server(handle_render_ping, "0.0.0.0", port)
        asyncio.get_event_loop().create_task(server.serve_forever())
        print(f"🌐 Keep-alive server on port {port}", flush=True)
    except Exception as e:
        print(f"⚠️  Keep-alive server failed: {e}", flush=True)

    asyncio.get_event_loop().create_task(self_ping_loop())
    asyncio.get_event_loop().create_task(patch_scraper_loop())

    print(f"✨ Answer model pool: {ANSWER_MODELS}")
    print(f"💬 Casual model pool: {CASUAL_MODELS}")
    print("🌸 Hafu is ready to reluctantly answer questions from the lobby.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # ── Passive history capture (every non-bot message) ──────────────────────
    cid = message.channel.id
    if cid not in channel_history:
        channel_history[cid] = deque(maxlen=HISTORY_WINDOW)
    clean_content = re.sub(r"<@!?\d+>", "", message.clean_content).strip()
    if clean_content:
        channel_history[cid].append((
            message.author.display_name,
            clean_content[:HISTORY_MSG_CAP],
        ))

    # ── Only respond when mentioned ──────────────────────────────────────────
    if bot.user not in message.mentions:
        return

    question = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not question:
        question = "hello"

    if not GROQ_TOKEN:
        await message.reply(
            "Omg my GROQ_TOKEN is missing — did someone forget the env var?! *taps foot*"
        )
        return

    # Gather context (instant, no API calls)
    chat_ctx = get_chat_context(cid)
    user_mem = get_user_profile(message.author.id)

    async with message.channel.typing():

        # ── Fast path: obviously casual — skip the triage API call ────────────
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "")
            text_out = await get_answer_casual([
                {"role": "system", "content": build_system_with_time(CASUAL_SYSTEM)},
                {"role": "user",   "content": user_content},
            ])
            final = text_out[:1990] if len(text_out) > 1990 else text_out
            await message.reply(final)
            store_bot_reply(cid, final)
            asyncio.create_task(maybe_update_memory(
                message.author.id, message.author.display_name, question, text_out
            ))
            return

        # ── Binary triage — no key routing needed anymore ─────────────────────
        print(f"🔍 Triage: '{question[:60]}'", flush=True)
        needs_game = await triage(question)

        if not needs_game:
            print("   ──► Casual (triage)", flush=True)
            user_content = build_answer_content(question, chat_ctx, user_mem, "")
            text_out = await get_answer_casual([
                {"role": "system", "content": build_system_with_time(CASUAL_SYSTEM)},
                {"role": "user",   "content": user_content},
            ])
            final = text_out[:1990] if len(text_out) > 1990 else text_out
            await message.reply(final)
            store_bot_reply(cid, final)
            asyncio.create_task(maybe_update_memory(
                message.author.id, message.author.display_name, question, text_out
            ))
            return

        # ── Semantic guide search via ChromaDB (change #1 + #6) ───────────────
        print(f"   ──► Game question — semantic guide search", flush=True)
        game_ctx = search_guides(question, n_results=4)
        if not game_ctx:
            print("   ⚠️  No guide results — answering from personality", flush=True)

        user_content = build_answer_content(question, chat_ctx, user_mem, game_ctx)
        text_out = await get_answer([
            {"role": "system", "content": build_system_with_time(ANSWER_SYSTEM)},
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

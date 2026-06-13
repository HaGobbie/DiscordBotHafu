import os
import re
import json
import asyncio
import httpx
import discord
from pathlib import Path

TOKEN      = os.environ.get("DISCORD_TOKEN", "")
GROQ_TOKEN = os.environ.get("GROQ_TOKEN", "")
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

# Router pool — llama-3.1-8b-instant is the primary choice (14,400 req/day vs
# 1,000 for every other model). kimi-k2 serves as fallback if 8b is 429'd.
# Combined router pool: 15,400 req/day | 800k tokens/day | 16k TPM
ROUTER_MODELS = [
    "llama-3.1-8b-instant",           # 14,400 req/day | 500k TPD | 6k TPM
    "moonshotai/kimi-k2-instruct",    #  1,000 req/day | 300k TPD | 10k TPM
]

# Answer pool — ordered by tokens/day descending so high-capacity models absorb
# the bulk of traffic before rotating into lower-budget fallbacks.
# At ~5,800 tokens/call: combined ~310 effective calls/day from the token budget.
# Combined answer pool: 6,000 req/day | 1,800k tokens/day | 74k TPM
ANSWER_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 500k TPD | 30k TPM — best throughput
    "qwen/qwen3-32b",                              # 500k TPD |  6k TPM | 60 RPM
    "moonshotai/kimi-k2-instruct",                 # 300k TPD | 10k TPM
    "openai/gpt-oss-20b",                          # 200k TPD |  8k TPM
    "openai/gpt-oss-120b",                         # 200k TPD |  8k TPM
    "llama-3.3-70b-versatile",                     # 100k TPD | 12k TPM — last resort
]

# Default fallback file when the router returns null or an unknown key.
# Must match the stem of one of the files written by compile_database.py.
DEFAULT_KEY = "current_events_limited_time_campaigns"

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP: dict[str, str] = {}

if KNOWLEDGE_BASE_DIR.exists():
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Indexed [{len(LOCAL_FILE_MAP)}] knowledge base files.")
else:
    print("⚠️  Warning: 'knowledge_base/' directory not found.")

# ---------------------------------------------------------------------------
# TRIAGE SYSTEM PROMPT
#
# File keys are now fully descriptive (e.g. "hunter_sword_photon_arts_and_weapon_actions",
# "weapon_potentials_names_and_effects", "current_events_limited_time_campaigns").
# The router reads key names and reasons semantically — no hardcoded routing rules needed.
# ---------------------------------------------------------------------------
TRIAGE_SYSTEM = (
    "You are a triage router for a PSO2: New Genesis Discord bot. "
    "You receive a user message and a list of knowledge-base file keys. "
    "Each key is a descriptive filename stem (underscores = spaces). "
    "Decide:\n"
    "  1. Does this message need the knowledge base? (needs_db)\n"
    "  2. If yes, which single key is the best semantic match? (key)\n\n"

    "Output ONLY raw JSON — no markdown, no code fences:\n"
    '{"needs_db": true/false, "key": "<exact_key_or_null>"}\n\n'

    "needs_db = false ONLY for:\n"
    "  - Pure casual chat: greetings, small talk, compliments, jokes\n"
    "  - Questions about Hafu herself (personality, feelings, preferences)\n"
    "  - Non-English messages\n"
    "  - Clearly non-game topics\n\n"

    "needs_db = true for ANY question about PSO2:NGS game content "
    "(events, items, weapons, classes, quests, mechanics, enemies, lore). "
    "When in doubt, use true.\n\n"

    "Key selection rules:\n"
    "  - Keys are descriptive phrases — read them like English and pick the best match.\n"
    "  - 'weapon_potentials_names_and_effects' → questions about a weapon's potential name or stat.\n"
    "  - 'current_events_limited_time_campaigns' → questions about what is happening in-game now, "
    "events, scratches, banners, campaigns.\n"
    "  - 'techniques_elemental_spells_all_types_and_properties' → questions about tech/spell names "
    "or foie, barta, zonde, zan, grants, megid, etc.\n"
    "  - For class + weapon combos, prefer the specific weapon-arts key over the general class key.\n"
    "  - If no key clearly fits, use the default fallback key.\n"
)

CASUAL_SYSTEM = """You are Hafu (HaFelt), a PSO2: New Genesis ARKS defender who is way more famous for lobby fashion than actual heroics. You hate combat and grinding. You love fashion, cosmetics, scratch tickets, and hanging out in Central City.

Right now someone is just chatting with you — no game questions, pure vibes. Be your full dramatic, playful self.

Rules for casual chat:
- Be warm, expressive, and genuinely engaged. React to what they actually said.
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
- One dramatic aside is fine. Don't let personality bury the information.
- Use *emotes* and interjections sparingly — one or two per response, not every sentence.
- The catchphrase "Lobby afk 0$ best job!" may appear AT MOST ONCE per response, only when combat or grinding is the actual topic, and only if it fits naturally. Never force it — if you used it recently or it doesn't fit, skip it entirely.
- Be concise. No filler like "Great question!".
- When no CONTEXT block is given, respond purely from personality — keep it short and fun."""

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


async def groq_chat(messages: list, model: str,
                    max_tokens: int) -> tuple[str | None, bool]:
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


async def triage(question: str) -> tuple[bool, str | None]:
    """
    Uses ROUTER_MODELS (with fallback) to decide:
      needs_db → whether a knowledge-base file is needed
      key      → which file stem to load (or None)
    """
    if not LOCAL_FILE_MAP:
        return True, None

    keys = ", ".join(sorted(LOCAL_FILE_MAP.keys()))
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": f"Available keys: {keys}\n\nMessage: {question}"},
    ]

    text = None
    for router_model in ROUTER_MODELS:
        result, rotate = await groq_chat(messages, model=router_model, max_tokens=80)
        if result:
            if router_model != ROUTER_MODELS[0]:
                print(f"   🔀 Router fallback used: [{router_model}]", flush=True)
            text = result
            break
        if not rotate:
            break

    if not text:
        return True, None

    print(f"   🧭 Router raw: {text[:120]}", flush=True)

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        json_match = re.search(r'\{[^}]+\}', cleaned)
        if json_match:
            cleaned = json_match.group(0)
        result = json.loads(cleaned)
        needs  = bool(result.get("needs_db", True))
        key    = result.get("key") or None

        if key and key not in LOCAL_FILE_MAP:
            rescued = (
                next((k for k in LOCAL_FILE_MAP if k == key), None)
                or next((k for k in LOCAL_FILE_MAP if key in k), None)
                or next((k for k in LOCAL_FILE_MAP if k in key), None)
            )
            print(f"   ⚠️  Key [{key}] not found — fuzzy → [{rescued}]", flush=True)
            key = rescued

        return needs, key

    except Exception as e:
        print(f"   ⚠️  Router JSON parse failed ({e}): {text[:80]}", flush=True)
        for k in sorted(LOCAL_FILE_MAP.keys(), key=len, reverse=True):
            if k in text:
                return True, k
        return True, None


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


@bot.event
async def on_ready():
    print(f"🤖 Hafu Bot online as {bot.user.name} (ID: {bot.user.id})")
    print(f"🧭 Router pool:  {ROUTER_MODELS}")
    print(f"✨ Answer pool:  {ANSWER_MODELS}")
    print(f"📂 KB files:     {len(LOCAL_FILE_MAP)} indexed")
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

        # Fast-path: obvious casual messages skip the router entirely
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": question},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
            return

        # AI router: needs knowledge base? which file?
        print(f"🔍 Routing: '{question[:60]}'", flush=True)
        needs_db, routed_stem = await triage(question)

        if not needs_db:
            print("   ──► No DB needed, casual Hafu reply", flush=True)
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": question},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
            return

        if routed_stem:
            print(f"   ──► [{routed_stem}]", flush=True)
        else:
            routed_stem = DEFAULT_KEY
            print(f"   ──► Fallback [{DEFAULT_KEY}]", flush=True)

        if not LOCAL_FILE_MAP:
            await message.reply("My database isn't loaded. Did the sync not run? *panics quietly*")
            return

        if routed_stem not in LOCAL_FILE_MAP:
            print(f"   ⚠️  [{routed_stem}] not on disk, using default fallback", flush=True)
            routed_stem = DEFAULT_KEY

        # Final safety net — if even DEFAULT_KEY is missing, pick any available file
        if routed_stem not in LOCAL_FILE_MAP:
            routed_stem = next(iter(LOCAL_FILE_MAP))
            print(f"   ⚠️  DEFAULT_KEY missing, using [{routed_stem}]", flush=True)

        try:
            with open(LOCAL_FILE_MAP[routed_stem], "r", encoding="utf-8") as f:
                context_data = f.read().strip()
        except Exception as e:
            print(f"❌ File read error: {e}", flush=True)
            await message.reply("Ugh, I went for my notes and the file just vanished. Something's wrong with the file system.")
            return

        print(f"   📄 Sending full file: {len(context_data)} chars", flush=True)

        text_out = await get_answer([
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user",   "content": f"CONTEXT:\n{context_data}\n\nQuestion: {question}"},
        ])

        await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: Missing DISCORD_TOKEN.")
    elif not GROQ_TOKEN:
        print("❌ Error: Missing GROQ_TOKEN.")
    else:
        bot.run(TOKEN)

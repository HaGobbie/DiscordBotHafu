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
bot = discord.Client(intents=intents)

KNOWLEDGE_BASE_DIR = Path("./knowledge_base")
LOCAL_FILE_MAP: dict[str, str] = {}

if KNOWLEDGE_BASE_DIR.exists():
    for txt_file in KNOWLEDGE_BASE_DIR.rglob("*.txt"):
        LOCAL_FILE_MAP[txt_file.stem] = str(txt_file)
    print(f"📦 Indexed [{len(LOCAL_FILE_MAP)}] knowledge base files.")
else:
    print("⚠️  Warning: 'knowledge_base/' directory not found.")

TRIAGE_SYSTEM = (
    "You are a triage router for a PSO2: New Genesis Discord bot named Hafu. "
    "Your job: decide if the message needs the game knowledge base, and if so, "
    "pick the single best matching key from the available keys list. "
    "Output ONLY valid JSON with no extra text: {\"needs_db\": true/false, \"key\": \"<exact_key_or_null>\"}. "
    "\n\nneeds_db=false for: greetings, small talk, jokes, compliments, personal messages, "
    "questions about Hafu herself, non-English messages, follow-up chat, anything "
    "that is NOT specifically asking about PSO2:NGS game mechanics, items, quests, or content. "
    "When in doubt, default to needs_db=false. "
    "\n\nneeds_db=true ONLY when the message explicitly asks for PSO2:NGS game information. "
    "When needs_db=true, set key to the single most relevant key from the available list. "
    "\n\nKey selection rules:"
    "\n- Current events, limited banners, scratch, seasonal campaigns → frontpage"
    "\n- Patch notes, maintenance, SEGA announcements → sega_live_feed"
    "\n- Mission pass → mission_pass"
    "\n- Weapon potentials / unlock potential → potentials"
    "\n- Best weapon / weapon series / meta gear → weapon_series"
    "\n- Class question + no specific weapon → <classname>_general (e.g. hunter_general)"
    "\n- Class question + specific weapon → <classname>_<weapon>_skills (e.g. hunter_sword_skills)"
    "\n- PA / photon art questions → <weapon>_pa_basics (e.g. sword_pa_basics)"
    "\n- Augments/affixes (system) → augments_system"
    "\n- Augments from boss/enemy drops → augments_boss"
    "\n- Augment enhance/XP/connector → augments_enhance"
    "\n- Special/duel/season augments → augments_special"
    "\n- Standard stat augments → augments_standard"
    "\n- Enemy types / rare / enhanced → enemy_types"
    "\n- Dolls / Alters → enemy_dolls_alters"
    "\n- Formers / Starless / Ruinus → enemy_formers_starless"
    "\n- If nothing clearly matches → frontpage"
    "\n\nNo explanation, no markdown, no code fences. Respond with raw JSON only."
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


def extract_relevant_sections(file_text: str, question: str,
                               max_chars: int = 4_000) -> str:
    """
    Split the file into sections, score each by keyword overlap with the
    question (stopwords excluded), and return only the top-scoring sections
    up to max_chars.

    Fallback when relevance is low: walk sections in document order up to
    max_chars — avoids the raw file[:max_chars] trap that grabs nav/TOC blobs
    which always sit at the top of the file.
    """
    _SW = {"the","and","for","not","you","are","was","but","what","how","who",
           "when","where","why","this","that","with","from","have","has","had",
           "will","can","may","its","our","are","were","been","being"}
    q_words = {w for w in re.findall(r"\b\w{3,}\b", question.lower()) if w not in _SW}
    if not q_words:
        return file_text[:max_chars]

    header_pattern = re.compile(
        r"(?m)^(?:#{1,3}\s+\S|(?=[A-Z\[]))[^\n]{1,80}$"
    )
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

    # Store (score, original_index, text) so we can restore document order later
    scored    = [(score(s), i, s) for i, s in enumerate(sections)]
    top_score = max(sc for sc, _, _ in scored)

    if top_score <= 1:
        # Low relevance: walk in document order so we get real content, not
        # the nav/TOC blob that always sits at the top of the raw file.
        result, total = [], 0
        for _sc, _idx, section in scored:
            if total + len(section) > max_chars:
                break
            result.append(section)
            total += len(section)
        extracted = "\n\n".join(result) if result else file_text[:max_chars]
        print(f"   📐 Low relevance (best={top_score}) — doc-order "
              f"{len(extracted)}/{len(file_text)} chars", flush=True)
        return extracted

    # High relevance: rank by score descending, pick greedily
    ranked = sorted(scored, key=lambda x: x[0], reverse=True)

    result, total = [], 0
    for sc, _idx, section in ranked:
        if total + len(section) > max_chars:
            if not result:
                # Best section alone exceeds budget — truncate it rather than
                # returning nothing or falling back to the file top.
                print(f"   📐 Best section > budget — truncating to {max_chars} chars "
                      f"(best={top_score})", flush=True)
                return section[:max_chars]
            break
        result.append(section)
        total += len(section)

    extracted = "\n\n".join(result)
    print(f"   📐 Section extract: {len(file_text)} → {len(extracted)} chars "
          f"({len(result)}/{len(sections)} sections, best={top_score})", flush=True)
    return extracted


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
    Uses the router model to decide:
      - needs_db: whether a knowledge-base file is needed
      - key:      which file stem to load (or None)
    """
    if not LOCAL_FILE_MAP:
        return True, None

    keys = ", ".join(sorted(LOCAL_FILE_MAP.keys()))
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": f"Available keys: {keys}\n\nMessage: {question}"},
    ]

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=60)
    if not text:
        return True, None

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        result  = json.loads(cleaned)
        needs   = bool(result.get("needs_db", True))
        key     = result.get("key") or None

        # Validate key exists; fuzzy-match if the model hallucinated a close variant
        if key and key not in LOCAL_FILE_MAP:
            exact = next((k for k in LOCAL_FILE_MAP if k == key), None)
            if not exact:
                exact = next((k for k in LOCAL_FILE_MAP if key in k), None)
            if not exact:
                exact = next((k for k in LOCAL_FILE_MAP if k in key), None)
            key = exact

        return needs, key
    except Exception:
        # JSON parse failed — scan raw text for any known key as a last resort
        for k in LOCAL_FILE_MAP:
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

        # Fast-path: obvious casual messages bypass the router entirely
        if is_casual(question):
            print(f"💬 Casual bypass: '{question[:60]}'", flush=True)
            text_out = await get_answer([
                {"role": "system", "content": CASUAL_SYSTEM},
                {"role": "user",   "content": question},
            ])
            await message.reply(text_out[:1990] if len(text_out) > 1990 else text_out)
            return

        # AI router decides: needs knowledge base? which file?
        print(f"🔍 Routing: '{question[:60]}'", flush=True)
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
            print("   ──► Fallback [frontpage]", flush=True)

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

        context_data = extract_relevant_sections(context_data, question)

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

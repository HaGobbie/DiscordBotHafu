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

# ---------------------------------------------------------------------------
# Key descriptions fed to the router alongside the raw key list.
# Keeps the system prompt compact while giving the model semantic context.
# ---------------------------------------------------------------------------
_KEY_HINTS = {
    "frontpage":              "current events, limited-time scratch/banners, what's happening now, seasonal campaigns",
    "sega_live_feed":         "SEGA patch notes, server maintenance, official game announcements",
    "mission_pass":           "mission pass tracks, season pass rewards, pass tiers",
    "weapon_series":          "which weapon series is best/meta, series comparison (Lexio vs Kougensei etc.), series list",
    "potentials":             "potential NAME, potential effect, unlock potential, potential levels — use this even if a series name like Lexio or Kougensei is mentioned",
    "ex_styles":              "EX style mechanics, EX style unlock",
    "class_overview":         "class system overview, sub-class rules, main/sub class restrictions",
    "techniques":             "technique/spell names and info — foie, barta, zonde, zan, gra, grants, megid, ilfoie, ilbarta, wind/fire/ice/lightning/light/dark tech",
    "addon_skills":           "add-on skills, how to unlock add-on, add-on skill list",
    "augments_system":        "how augmenting works, augment slots, capsule combining, augment overview",
    "augments_boss":          "augments dropped by bosses / gigas / dread enemies",
    "augments_enhance":       "enhance / XP / connector / adi / nadi / ladi augments",
    "augments_special":       "duel / season / limited special augments",
    "augments_standard":      "stamina / power / shoot / technique / resist stat augments",
    "limit_breaking":         "limit break, raising item level cap, limit break materials",
    "equipment_enhancement":  "weapon/armor grinding, enhancement levels, how to +30/+40",
    "armor":                  "armor units, defensive units, armor stats",
    "quick_food":             "quick food, food buffs, buff stand, cooking recipes",
    "preset_abilities":       "preset abilities, preset skill",
    "multi_weapon":           "multi-weapon system, how to combine weapons",
    "combat_power":           "combat power, battle power, BP requirements",
    "status_effects":         "ailments, burn/freeze/shock/panic/blind, status effect resistance",
    "urgent_quests":          "urgent quests, emergency quests, EQ schedule",
    "battledia":              "battledia quests, battledia red/yellow/blue",
    "duel_quests":            "duel quests, solo combat challenges",
    "leciel_exploration":     "Leciel Exploration zone",
    "gathering":              "gathering, field materials, ore, fish, farming",
    "tasks":                  "daily tasks, weekly tasks, side quests",
    "titles_quests_tasks":    "titles earned from quests / tasks / map communication",
    "titles_player_items":    "title rewards, player titles, achievement titles",
    "enemy_types":            "enemy types, rare enemies, enhanced enemies, megalotix, dread",
    "enemy_dolls_alters":     "Doll enemies, Alter enemies",
    "enemy_formers_starless": "Former enemies, Starless, Ruinus enemies",
    "npc_profiles":           "NPC characters",
    "worldview_story":        "main story, chapters, lore, Halpha worldview",
    # classes — general
    "hunter_general":         "Hunter class general skills and overview",
    "fighter_general":        "Fighter class general skills and overview",
    "braver_general":         "Braver class general skills and overview",
    "bouncer_general":        "Bouncer class general skills and overview",
    "force_general":          "Force class general skills and overview",
    "techter_general":        "Techter class general skills and overview",
    "ranger":                 "Ranger class skills",
    "gunner":                 "Gunner class skills",
    "waker":                  "Waker class skills",
    "slayer":                 "Slayer class skills",
    # classes — weapon axis
    "hunter_sword_skills":        "Hunter sword-specific skills",
    "hunter_wired_skills":        "Hunter wired lance-specific skills",
    "hunter_partisan_skills":     "Hunter partisan-specific skills",
    "fighter_dagger_skills":      "Fighter twin dagger skills",
    "fighter_saber_skills":       "Fighter double saber skills",
    "fighter_knuckle_skills":     "Fighter knuckle skills",
    "braver_katana_skills":       "Braver katana skills",
    "braver_rifle_skills":        "Braver assault rifle skills",
    "bouncer_dual_blade_skills":  "Bouncer dual blade skills",
    "bouncer_jet_boots_skills":   "Bouncer jet boots skills",
    "force_rod_skills":           "Force rod skills",
    "force_talis_skills":         "Force talis skills",
    "techter_wand_skills":        "Techter wand skills",
    "techter_talis_skills":       "Techter talis skills",
    "techter_subclass":           "Techter as a subclass",
}

def _build_triage_system() -> str:
    hint_block = "\n".join(
        f'  "{k}": {v}' for k, v in _KEY_HINTS.items()
    )
    return (
        "You are a triage router for a PSO2: New Genesis Discord bot named Hafu. "
        "Decide if a message needs the game knowledge base and, if so, pick the single "
        "best key from the available keys list.\n"
        "Output ONLY raw JSON — no markdown, no code fences, no explanation:\n"
        '{"needs_db": true/false, "key": "<exact_key_or_null>"}\n\n'

        "needs_db=false for: greetings, small talk, jokes, compliments, personal messages, "
        "questions about Hafu herself, non-English messages, casual follow-ups, anything "
        "NOT specifically about PSO2:NGS mechanics, items, quests, or content. "
        "When in doubt, use needs_db=false.\n\n"

        "needs_db=true only for explicit PSO2:NGS game questions. "
        "When true, pick the SINGLE best key. "
        "CRITICAL disambiguation rules (apply before anything else):\n"
        '  • Asking what a potential is NAMED, or its effect/level → "potentials" '
        '    (even if a series name like Lexio or Kougensei appears in the question)\n'
        '  • Asking which series is best/meta/recommended → "weapon_series"\n'
        '  • Technique/spell names (foie, barta, zan, wind tech, fire tech, etc.) → "techniques"\n'
        '  • Class + specific weapon combo → <class>_<weapon>_skills '
        '    (e.g. hunter_sword_skills, techter_wand_skills)\n'
        '  • Class question with no weapon → <class>_general\n'
        '  • PA / photon art moves → <weapon>_pa_basics (e.g. sword_pa_basics)\n'
        '  • Nothing clearly matches → "frontpage"\n\n'

        "Key hint index (use for additional context):\n"
        + hint_block
    )

TRIAGE_SYSTEM = _build_triage_system()

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


def _score_text(text: str, q_words: set[str]) -> int:
    """Count overlapping non-stopword words between text and question."""
    return len(q_words & set(re.findall(r"\b\w{3,}\b", text.lower())))


def _best_subchunk(section: str, q_words: set[str], max_chars: int) -> str:
    """
    When a single section is larger than max_chars, score each paragraph within
    it and return the highest-scoring contiguous group that fits in the budget.
    Falls back to a simple head-truncation only if there is no paragraph structure.
    """
    paras = [p.strip() for p in re.split(r"\n{2,}", section) if p.strip()]
    if len(paras) <= 1:
        return section[:max_chars]

    scored_paras = [(p, _score_text(p, q_words)) for p in paras]

    # Greedy: pick paragraphs by score, highest first, up to budget
    ranked = sorted(scored_paras, key=lambda x: x[1], reverse=True)
    chosen, total = [], 0
    for para, _ in ranked:
        if total + len(para) + 2 > max_chars:
            break
        chosen.append(para)
        total += len(para) + 2

    if not chosen:
        # Even the best paragraph is over budget; truncate it
        return ranked[0][0][:max_chars]

    # Re-order chosen paragraphs back to document order for readability
    para_order = {p: i for i, (p, _) in enumerate(scored_paras)}
    chosen.sort(key=lambda p: para_order.get(p, 0))
    return "\n\n".join(chosen)


def extract_relevant_sections(file_text: str, question: str,
                               max_chars: int = 5_000) -> str:
    """
    Split the file into header-delimited sections, score each by keyword overlap
    with the question, and return the best-scoring sections up to max_chars.

    Oversized section handling: when the single best section is larger than the
    budget, sub-split it by paragraph and pick the most relevant paragraphs
    instead of blindly truncating from the beginning.

    Low-relevance fallback: walk sections in document order (not raw file top)
    to avoid returning nav/TOC blobs that sit at the start of every file.
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

    # (score, original_doc_index, text)
    scored    = [(_score_text(s, q_words), i, s) for i, s in enumerate(sections)]
    top_score = max(sc for sc, _, _ in scored)

    if top_score <= 1:
        # Low relevance — walk in document order (skips nav/TOC blob at file top)
        result, total = [], 0
        for _sc, _idx, section in scored:
            if total + len(section) + 2 > max_chars:
                break
            result.append(section)
            total += len(section) + 2
        extracted = "\n\n".join(result) if result else file_text[:max_chars]
        print(f"   📐 Low relevance (best={top_score}) — doc-order "
              f"{len(extracted)}/{len(file_text)} chars", flush=True)
        return extracted

    # High relevance — rank by score descending, pick greedily
    ranked = sorted(scored, key=lambda x: x[0], reverse=True)

    result, total = [], 0
    for sc, _idx, section in ranked:
        if total + len(section) + 2 > max_chars:
            if not result:
                # Best section alone exceeds budget — sub-split by paragraph
                sub = _best_subchunk(section, q_words, max_chars)
                print(f"   📐 Oversized section sub-split: "
                      f"{len(section)} → {len(sub)} chars (best={top_score})", flush=True)
                return sub
            break
        result.append(section)
        total += len(section) + 2

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
    Uses llama-3.1-8b-instant to decide:
      needs_db → whether a knowledge-base file is needed
      key      → which file stem to load (or None for casual)
    """
    if not LOCAL_FILE_MAP:
        return True, None

    keys = ", ".join(sorted(LOCAL_FILE_MAP.keys()))
    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user",   "content": f"Available keys: {keys}\n\nMessage: {question}"},
    ]

    text, _ = await groq_chat(messages, model=ROUTER_MODEL, max_tokens=150)
    if not text:
        return True, None

    print(f"   🧭 Router raw: {text[:120]}", flush=True)

    try:
        cleaned = re.sub(r"```[a-z]*|```", "", text).strip()
        # Handle cases where the model wraps JSON in extra text
        json_match = re.search(r'\{[^}]+\}', cleaned)
        if json_match:
            cleaned = json_match.group(0)
        result = json.loads(cleaned)
        needs  = bool(result.get("needs_db", True))
        key    = result.get("key") or None

        # Validate key exists in the map; fuzzy-rescue hallucinated variants
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
        # Scan raw text for any known key as last resort
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

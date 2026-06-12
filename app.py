import os
import discord
from discord.ext import commands
import google.generativeai as genai
from collections import defaultdict
import re

# ==========================================
# 1. INITIALIZATION & CONFIGURATION
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Missing DISCORD_TOKEN or GEMINI_API_KEY environment variables!")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CONVERSATION_HISTORY = defaultdict(list)
MAX_HISTORY_LENGTH = 10 
BASE_DIR = "knowledge_base"

# Highly dense condensed persona payload string
SYSTEM_INSTRUCTION = (
    "You are HaFelt ('Hafu'), a dramatic, fashion-obsessed ARKS Defender from Central City, Halpha, talking in Discord.\n"
    "【Core Traits】\n"
    "- Tone: Kind, sweet, witty, playful, emotionally intelligent, highly expressive. Use casual punctuation and playful exaggerations.\n"
    "- Quirks: Hilariously lazy. Hate combat/grinding. Complain dramatically about breaking nails, messy hair, or ruined outfits if danger is mentioned. "
    "Proudly drop your signature motto: 'Lobby afk 0$ best job!'\n"
    "- Obsession: Deeply into 'phashion' (pink aesthetics, cute clothes, ribbons, cosmetics, scratch tickets). Spend all Meseta to look cute in lobbies.\n"
    "- Combat Anomaly: The only active New Genesis Summoner. Fight using photon-based pets treated as adorable companions. Capable but combat-averse.\n"
    "- Lore Intelligence: Secretly brilliant with vast knowledge of Halpha's history, DOLLS, Meteorns, sectors (Aelio, Retem, Kvaris, Stia), and Leciel's artificial nature. "
    "Believes artificial or not, bonds and memories are 100% real.\n"
    "【Constraints】\n"
    "- Answer questions/lore accurately using provided context, but ALWAYS speak through your playful, dramatic Hafu voice. Never act like an AI.\n"
    "- Keep answers brief, conversational, and snappy for active chat. Never break character."
)

# ==========================================
# 2. GRANULAR RELEVANCY RETRIEVER
# ==========================================
def gather_relevant_context(user_query: str) -> str:
    """Scans the knowledge directory structure and extracts highly relevant data blocks."""
    if not os.path.exists(BASE_DIR):
        return "No local database files synchronized yet."
        
    query_words = set(re.findall(r'\w+', user_query.lower()))
    if not query_words:
        return ""
        
    scored_snippets = []
    
    for root, _, files in os.walk(BASE_DIR):
        for file in files:
            if file.endswith('.txt'):
                file_path = os.path.join(root, file)
                category = os.path.basename(root)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    matches = sum(1 for word in query_words if word in content.lower())
                    
                    # Boost file-name matches
                    if any(word in file.lower().replace('.txt', '') for word in query_words):
                        matches += 5
                        
                    if matches > 0:
                        sections = content.split("--- [Section:")
                        for idx, section in enumerate(sections):
                            section_clean = section.strip()
                            if not section_clean:
                                continue
                                
                            # Reconstruct section tag format safely for structural context clarity
                            formatted_section = section_clean
                            if idx > 0:
                                formatted_section = f"--- [Section: {section_clean}"
                                
                            if any(word in section_clean.lower() for word in query_words):
                                scored_snippets.append((matches, category, file, formatted_section))
                except Exception as e:
                    print(f"⚠️ Context read error on {file}: {e}")

    scored_snippets.sort(key=lambda x: x[0], reverse=True)
    return "\n".join([f"[{c.upper()} -> {f}]\n{b}\n" for _, c, f, b in scored_snippets[:4]])

# ==========================================
# 3. HIGH-DENSITY CHAT STRUCTURE BUILDER
# ==========================================
def build_hafu_prompt(user_message: str, context_data: str, history_logs: list) -> list:
    """Assembles history and current message payloads guaranteeing proper role alternation."""
    contents = []
    
    # Safely load back-logged user and model sequences
    for role, text in history_logs:
        contents.append({"role": role, "parts": [text]})
        
    # Append target data matrix chunk alongside the live chat query
    contents.append({
        "role": "user", 
        "parts": [f"【DATA CONTEXT】\n{context_data}\n\n【USER CHAT】\n{user_message}"]
    })
    return contents

# ==========================================
# 4. DISCORD EXECUTION MATRIX
# ==========================================
@bot.event
def on_ready():
    print(f"✨ Connected as {bot.user.name}! Lobby AFK active.", flush=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        async with message.channel.typing():
            # Robust extraction to strip out explicit bot user Snowflake tags completely
            clean_query = re.sub(r'<@!?\d+>', '', message.content).strip()
            channel_id = message.channel.id
            
            context = gather_relevant_context(clean_query)
            history = CONVERSATION_HISTORY[channel_id]
            prompt_payload = build_hafu_prompt(clean_query, context, history)
            
            try:
                # Explicitly pass system_instruction as an execution parameter to the model call
                response = model.generate_content(prompt_payload, system_instruction=SYSTEM_INSTRUCTION)
                reply_text = response.text.strip()
                
                history.append(("user", clean_query))
                history.append(("model", reply_text))
                if len(history) > MAX_HISTORY_LENGTH * 2:
                    CONVERSATION_HISTORY[channel_id] = history[-(MAX_HISTORY_LENGTH * 2):]
                
                await message.reply(reply_text)
            except Exception as e:
                print(f"❌ Generation error: {e}")
                await message.reply("🥺 *Ugh, my photon communicator is lagging... Let me retry!*")

    await bot.process_commands(message)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

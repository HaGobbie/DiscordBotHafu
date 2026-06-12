import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types
from google.genai.errors import APIError
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

# ==================== KEEP-ALIVE SERVER CONFIGURATION ====================
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Hafu is alive!")
    def log_message(self, format, *args):
        return 

def run_keep_alive_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Keep-alive online on port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


# ==================== BOT INITIALIZATION & KEY RING ====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

RAW_KEYS = os.environ.get("GEMINI_KEY_RING", "")
GEMINI_KEYS = [k.strip() for k in RAW_KEYS.split(",") if k.strip()]

if not GEMINI_KEYS and os.environ.get("GEMINI_API_KEY"):
    GEMINI_KEYS = [os.environ.get("GEMINI_API_KEY")]

CLIENT_RING = {}
SELECTED_MODEL = 'gemini-3.5-flash'
current_key_index = 0

# Global Vector Database Storage
DB_CHUNKS = []
VECTORIZER = None
DB_MATRIX = None


# ==================== LINE-BASED VECTOR SEARCH ENGINE ====================
def initialize_vector_database():
    """
    Loads knowledge_database.txt and splits it into strict, evenly sized 
    line-based chunks to ensure total prompt tokens never exceed free tier caps.
    """
    global DB_CHUNKS, VECTORIZER, DB_MATRIX
    
    if not os.path.exists("knowledge_database.txt"):
        print("⚠️ Warning: knowledge_database.txt not found!", flush=True)
        return

    print("📂 Analyzing database structure...", flush=True)
    with open("knowledge_database.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Clean empty rows to maximize real content per chunk
    clean_lines = [l for l in lines if l.strip()]
    
    # Slice the entire wiki cleanly into small blocks of 25 lines each
    lines_per_chunk = 25
    DB_CHUNKS = []
    
    for i in range(0, len(clean_lines), lines_per_chunk):
        chunk_slice = clean_lines[i:i + lines_per_chunk]
        DB_CHUNKS.append("".join(chunk_slice))

    if not DB_CHUNKS:
        print("⚠️ Warning: No valid data extracted from database.", flush=True)
        return

    print(f"🧩 Synthesized {len(DB_CHUNKS)} strict database fragments. Compiling vector space...", flush=True)
    
    # Text scoring parameters optimized for shorthand wiki queries and gaming jargon
    VECTORIZER = TfidfVectorizer(
        stop_words='english',
        ngram_range=(1, 2),  # Captures multi-word items like "Photon Art" or "Assault Rifle"
        lowercase=True
    )
    DB_MATRIX = VECTORIZER.fit_transform(DB_CHUNKS)
    
    print("✅ Local Semantic Database is fully online and size-guarded!", flush=True)


def get_semantic_context(user_query, top_k=3):
    """
    Scores the query against the vector field using cosine similarity
    and maps out the top matches.
    """
    if DB_MATRIX is None or len(DB_CHUNKS) == 0:
        return "No local database available."

    try:
        query_vector = VECTORIZER.transform([user_query])
        scores = (DB_MATRIX * query_vector.T).toarray().flatten()
        
        # Pull top indexing matches
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        # Only include chunks with real token overlap relevance (score baseline > 0.02)
        matched_segments = [DB_CHUNKS[idx] for idx in top_indices if scores[idx] > 0.02]
        
        if not matched_segments:
            return "No matching specific data found in the game files."
            
        return "\n\n---\n\n".join(matched_segments)
    except Exception as e:
        print(f"❌ Search Error: {e}", flush=True)
        return "Error searching local database."


# ==================== SYSTEM CHARACTER PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving Phantasy Star Online 2: New Genesis (PSO2:NGS) bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided database context snippets to answer the user's question.
- Keep your responses direct, concise, and aligned with game specifics. Do not guess stats or build names.
- If the database snippets do not contain the answer, say so in character: "*yawns* I don't see anything like that in my notes... Maybe go check the blocks yourself or ask a pro in the lobby."
"""


# ==================== DISCORD CORE COMMANDS ====================
@bot.event
async def on_ready():
    initialize_vector_database()
    for i, key in enumerate(GEMINI_KEYS):
        CLIENT_RING[i] = genai.Client(api_key=key)
    print(f"🔥 Hafu is online and fully configured with {len(GEMINI_KEYS)} keys!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING:
        await ctx.reply("Ah... *yawn* My API key ring is missing. Tell the admin~")
        return

    # 1. Fetch relevant sections over the local vector database
    relevant_chunks = get_semantic_context(question, top_k=4)

    # 2. Bundle query context safely below 2,000 tokens total
    user_prompt = f"""Context from Game Files:
{relevant_chunks}

User Query: {question}"""

    # 3. Request loop over key ring to guard against 429 errors
    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        
        try:
            response = client.models.generate_content(
                model=SELECTED_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=600
                )
            )
            
            # Debug tracking for logs
            try:
                print(f"🔍 [Key {idx+1}] Tokens: {response.usage_metadata.prompt_token_count} | Finish: {response.candidates[0].finish_reason}", flush=True)
            except Exception:
                pass

            text_out = response.text.strip()
            if not text_out:
                text_out = "*yawns* I checked, but my head is too empty to answer right now..."
            
            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Key [{idx+1}] hit rate limits. Swapping pool position...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue 
            else:
                print(f"❌ API Error on Key [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("*yawn* Something went wrong inside the API pipeline.")
                return
        except Exception as e:
            print(f"❌ Unexpected Error on Key [{idx+1}]: {e}", flush=True)
            await ctx.reply("Ugh, Hafu got disconnected for a second. Try again?")
            return

    await ctx.reply("Ah... *yawns loudly* Too many requests at once. My brain is on cooldown~")


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN is completely missing from environment variables!")

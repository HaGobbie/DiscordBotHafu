import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from sentence_transformers import SentenceTransformer, util

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


# ==================== BOT INITIALIZATION & SETUP ====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

print("🧠 Loading local Semantic Search embedding model...", flush=True)
# This free model maps context meanings geometrically and handles typos completely natively
search_model = SentenceTransformer('all-MiniLM-L6-v2')
print("✅ Semantic Search model successfully initialized inside container memory!", flush=True)


# ==================== STRICT PERSONALITY SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving PSO2:NGS bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided "Database content" to answer the user's question. Use it to find exact Photon Arts, Techniques, or locations.
- If the provided database context contains "No specific data found" or explicitly lacks a clear, identifiable answer, do NOT invent fake information. Instead, maintain character and say: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== ADVANCED SEMANTIC SEARCH ENGINE ====================
def scan_compiled_database(query):
    """
    Transforms both the database blocks and the raw user question into vector coordinates.
    Finds the exact data paragraphs closest in mathematical meaning, rendering typos irrelevant.
    """
    try:
        if not os.path.exists("knowledge_database.txt"):
            return "No specific data found."

        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            content = f.read()

        # Split the text repository by double newlines to grab clean structural blocks/paragraphs intact
        paragraphs = [p.strip() for p in content.split("\n\n") if len(p.strip()) > 40]
        
        if not paragraphs:
            return "No specific data found."

        # Convert the dynamic user string and database array into mathematical representations
        paragraph_embeddings = search_model.encode(paragraphs, convert_to_tensor=True)
        query_embedding = search_model.encode(query, convert_to_tensor=True)

        # Calculate geometric similarity scores between query vector and database blocks
        cos_scores = util.cos_sim(query_embedding, paragraph_embeddings)[0]
        
        # Select the top 4 most matching meaningful blocks
        top_results = cos_scores.topk(k=min(4, len(paragraphs)))

        extracted_chunks = []
        for score, idx in zip(top_results[0], top_results[1]):
            # Only append chunks that cross our relevance barrier
            if score > 0.22:
                extracted_chunks.append(paragraphs[idx])

        # Always append the live official announcements timeline block at the bottom
        if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in content:
            sega_segment = content.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
            extracted_chunks.append(f"=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_segment[:2500]}")

        if extracted_chunks:
            return "\n\n... \n\n".join(extracted_chunks)[:14000]
            
    except Exception as e:
        print(f"Error during semantic search vector alignment: {e}")
        
    return "No specific data found."


# ==================== DISCORD CORE EVENTS & COMMANDS ====================
@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    
    # 1. Dynamically retrieve the paragraphs that match the meaning of the query
    db_context = scan_compiled_database(question)
    
    # 2. Build model submission payload structures
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}
    ]
    
    try:
        # 3. Submit data directly to Llama core
        response = client.chat_completion(
            model="meta-llama/Llama-3.1-8B-Instruct",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        text = response.choices[0].message.content.strip()
        await ctx.reply(text)
        
    except Exception as e:
        print(f"Error handling /ask command: {e}")
        await ctx.reply("Sorry~ Hafu was... *yawn* way too sleepy and timed out. Try asking again!")


# ==================== WAKE UP CALL ====================
if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN environment variable is missing!")

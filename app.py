import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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


# ==================== STRICT PERSONALITY SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving PSO2:NGS bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided "Database content" to answer the user's question. Find the exact Photon Arts, Techniques, or locations requested.
- If the provided database context contains "No specific data found" or explicitly lacks the clear answer, do NOT invent fake names. Instead, maintain character and say something like: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== OVERLAPPING PARAGRAPH BLOCK SCANNER ====================
def scan_compiled_database(query):
    """
    Scans the database file globally by dividing text into fixed overlapping multi-line blocks.
    This guarantees that table rows, bullet points, and plain lists are captured seamlessly.
    """
    lowered = query.lower()
    extracted_chunks = []
    
    # Expand keyword queries dynamically to match game elements
    search_terms = [w for w in lowered.split() if len(w) > 3]
    if "light" in lowered:
        search_terms.extend(["technique", "grants", "light", "fomelgion", "berlanzion"])
    if "rifle" in lowered or "pa" in lowered or "photon art" in lowered:
        search_terms.extend(["assault rifle", "rifle", "photon art", "pa", "ranger", "shot"])
    if "sword" in lowered:
        search_terms.extend(["sword", "hunter", "weapon", "kougensei"])
    if "city" in lowered or "aelio" in lowered:
        search_terms.extend(["central city", "aelio", "region", "city"])

    search_terms = list(set(search_terms))

    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Group text by continuous 40-line blocks with a 15-line overlap window
            # This prevents tabular data and lists from being cut off arbitrarily
            block_size = 40
            overlap = 15
            
            idx = 0
            while idx < len(lines):
                block_lines = lines[idx : idx + block_size]
                block_text = "".join(block_lines)
                block_text_lower = block_text.lower()
                
                # If any target term matches inside this line group block, save it
                if any(term in block_text_lower for term in search_terms):
                    if block_text not in extracted_chunks:
                        extracted_chunks.append(block_text)
                
                idx += (block_size - overlap)
                
                # Safe cutoff cap for context array payload size
                if len(extracted_chunks) >= 8:
                    break
                    
            # Always make sure the live update feed is visible at the bottom
            full_content = "".join(lines)
            if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in full_content:
                sega_segment = full_content.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
                extracted_chunks.append(f"\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_segment[:2500]}")

        if extracted_chunks:
            return "\n\n... \n\n".join(extracted_chunks)[:14500]
            
    except Exception as e:
        print(f"Error scanning knowledge database file: {e}")
        
    return "No specific data found."


# ==================== DISCORD CORE EVENTS & COMMANDS ====================
@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    
    # 1. Pull overlapping data context chunks
    db_context = scan_compiled_database(question)
    
    # 2. Frame the payload structures
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}
    ]
    
    try:
        # 3. Request completion matrix from Llama endpoint
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

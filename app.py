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
- STRICT RULE: You MUST rely ONLY on the provided "Database content" to answer the user's question. 
- If the provided database context contains "No specific data found" or lacks the clear answer, do NOT invent fake weapon names, fake photon arts, or fake techniques. Instead, maintain character and say something like: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== GLOBAL PARAGRAPH-MATCHING SCANNER ====================
def scan_compiled_database(query):
    """
    Scans the entire database file globally. Instead of splitting by massive 
    page headings, it extracts lines and paragraphs containing direct keyword 
    hits to prevent truncation issues.
    """
    lowered = query.lower()
    extracted_chunks = []
    
    # Map common player search phrases directly to relevant terminology terms
    search_terms = [w for w in lowered.split() if len(w) > 3]
    if "light" in lowered:
        search_terms.extend(["grants", "technique", "light"])
    if "rifle" in lowered:
        search_terms.extend(["assault rifle", "rifle", "photon art"])
    if "sword" in lowered:
        search_terms.extend(["sword", "hunter", "weapon"])
    if "city" in lowered or "aelio" in lowered:
        search_terms.extend(["central city", "aelio", "region"])

    # Remove duplicates
    search_terms = list(set(search_terms))

    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                full_text = f.read()
            
            # Split the entire document by sentence blocks/periods to find close context matches
            sentences = full_text.split(". ")
            
            current_context_chunk = []
            for idx, sentence in enumerate(sentences):
                sentence_lower = sentence.lower()
                
                # If a sentence contains any of our key metrics, grab it along with surrounding sentences
                if any(term in sentence_lower for term in search_terms):
                    # Pull preceding and proceeding lines for structural context cohesion
                    start = max(0, idx - 2)
                    end = min(len(sentences), idx + 3)
                    
                    context_snippet = ". ".join(sentences[start:end])
                    if context_snippet not in extracted_chunks:
                        extracted_chunks.append(context_snippet)
                
                # Safety cap to keep within context limits
                if len(extracted_chunks) >= 12:
                    break
                    
            # Always ensure seasonal live update visibility remains appended
            if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in full_text:
                sega_segment = full_text.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
                extracted_chunks.append(f"\n=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_segment[:2000]}")

        if extracted_chunks:
            return "\n\n... ".join(extracted_chunks)[:14000]
            
    except Exception as e:
        print(f"Error scanning knowledge database globally: {e}")
        
    return "No specific data found."


# ==================== DISCORD CORE EVENTS & COMMANDS ====================
@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    
    # 1. Fetch deep context blocks from the global registry file
    db_context = scan_compiled_database(question)
    
    # 2. Construct messages frame payload
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}
    ]
    
    try:
        # 3. Call Llama 3.1 Inference Engine endpoint 
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

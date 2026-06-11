import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import difflib

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
- STRICT RULE: You MUST rely ONLY on the provided "Database content" to answer the user's question. Use it to find exact Photon Arts, Techniques, or locations.
- If the provided database context contains "No specific data found" or explicitly lacks a clear, identifiable answer, do NOT invent fake information. Instead, maintain character and say: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== LOW-RAM FUZZY SEARCH ENGINE ====================
def scan_compiled_database(query):
    """
    Scans the database by splitting it into natural paragraph sections, then uses 
    fuzzy sequence matching to locate sections. Immune to typos, ultra low memory.
    """
    lowered_query = query.lower()
    extracted_chunks = []
    
    # Core game tags we want to look out for in user text to grab full sections
    game_keywords = ["rifle", "assault", "technique", "light", "sword", "hunter", "ranger", "aelio", "city", "central"]

    try:
        if not os.path.exists("knowledge_database.txt"):
            return "No specific data found."

        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            content = f.read()

        # Split file by structural page dividers or clean double returns
        sections = content.split("=== [")
        
        # Check for direct keyword matches or close fuzzy matches for typos (e.g. "rifel" -> "rifle")
        user_words = [w.strip("?,.!") for w in lowered_query.split() if len(w) > 3]
        
        for section in sections:
            if not section.strip():
                continue
                
            section_text = "=== [" + section
            section_lower = section_text.lower()
            
            is_match = False
            
            # Check every word the user typed using a fuzzy threshold (0.75 score matches mild typos)
            for word in user_words:
                # Direct string check
                if word in section_lower:
                    is_match = True
                    break
                
                # Typo checking against core keywords
                close_matches = difflib.get_close_matches(word, game_keywords, n=1, cutoff=0.75)
                if close_matches and close_matches[0] in section_lower:
                    is_match = True
                    break
            
            if is_match:
                # Snip a clean chunk from the matching section data
                extracted_chunks.append(section_text[:6000])
                
            if len(extracted_chunks) >= 3:
                break

        # Always append the live official announcements timeline block at the bottom
        if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in content:
            sega_segment = content.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
            extracted_chunks.append(f"=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_segment[:3000]}")

        if extracted_chunks:
            return "\n\n... \n\n".join(extracted_chunks)[:14000]
            
    except Exception as e:
        print(f"Error during fuzzy search execution: {e}")
        
    return "No specific data found."


# ==================== DISCORD CORE EVENTS & COMMANDS ====================
@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    
    # 1. Gather targeted sections via fuzzy character matching
    db_context = scan_compiled_database(question)
    
    # 2. Build model prompt frames
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}
    ]
    
    try:
        # 3. Request answer string from Llama
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

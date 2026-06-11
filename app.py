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


# ==================== BULLETPROOF CONTENT-KEYWORD SCANNER ====================
def scan_compiled_database(query):
    """
    Scans the translated knowledge_database.txt thoroughly by looking for keywords
    directly inside the section contents, capturing entire contextual blocks.
    """
    lowered = query.lower()
    extracted = []
    
    # Mapping to guide the scanner to include relevant adjacent content blocks
    category_map = {
        "technique": ["technique", "grants", "barta", "foie", "zonde", "foie"],
        "light": ["technique", "grants", "light element"],
        "rifle": ["assault rifle", "ranger", "rifle"],
        "assault": ["assault rifle"],
        "photon art": ["photon art", "pa", "hunter", "ranger", "fighter", "skills"],
        "pa": ["photon art", "pa", "skills"],
        "sword": ["sword", "hunter"],
        "weapon": ["weapon", "equipment", "sword", "rifle"],
        "armor": ["armor", "unit", "defense"],
        "central city": ["central city", "aelio", "city"],
        "aelio": ["aelio", "region"],
        "sega": ["sega", "announcements", "update"],
        "update": ["sega", "update", "patch"]
    }
    
    # Gather search tokens based on user question intent
    target_keywords = [w for w in lowered.split() if len(w) > 3]
    for key, keywords in category_map.items():
        if key in lowered:
            target_keywords.extend(keywords)
            
    # De-duplicate search criteria
    target_keywords = list(set(target_keywords))

    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Split using the plain header name delimiter
            sections = content.split("=== [")
            
            for section in sections:
                if not section.strip():
                    continue
                
                section_lower = section.lower()
                
                # Check if any target keywords appear anywhere in this entire text block
                if any(keyword in section_lower for keyword in target_keywords):
                    # Pull a massive, generous 5000 character segment from the match block
                    reconstructed = "=== [" + section[:5000]
                    extracted.append(reconstructed)
                
                # Cap the array length to stay safely within Llama's total context limits
                if len(extracted) >= 4:
                    break
            
            # Always make sure the live update feed is visible at the bottom
            if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in content:
                sega_segment = content.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
                extracted.append(f"=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_segment[:2500]}")

        if extracted:
            return "\n\n".join(extracted)[:14500]
            
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
    
    # 1. Fetch targeted search blocks from the database
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

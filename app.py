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


# ==================== INTELLIGENT DATABASE SCANNER ====================
def scan_compiled_database(query):
    """
    Scans the translated knowledge_database.txt thoroughly, mapping common 
    English game terminology directly to the translated wiki headers.
    """
    lowered = query.lower()
    extracted = []
    
    # Map common terms directly to what the scraper writes in the txt file headers
    category_map = {
        "technique": ["=== [テクニック] ==="],
        "light": ["=== [テクニック] ==="],
        "grant": ["=== [テクニック] ==="],
        "fire": ["=== [テクニック] ==="],
        "ice": ["=== [テクニック] ==="],
        "lightning": ["=== [テクニック] ==="],
        "wind": ["=== [テクニック] ==="],
        "dark": ["=== [テクニック] ==="],
        "rifle": ["=== [アサルトライフル] ===", "=== [レンジャー] ==="],
        "assault": ["=== [アサルトライフル] ==="],
        "photon art": ["=== [ハンター] ===", "=== [ファイター] ===", "=== [レンジャー] ===", "=== [ガンナー] ===", "=== [フォース] ===", "=== [テクター] ===", "=== [ブレイバー] ===", "=== [バウンサー] ===", "=== [ウェイカー] ===", "=== [スレイヤー] ==="],
        "pa": ["=== [ハンター] ===", "=== [レンジャー] ===", "=== [ブレイバー] ==="],
        "sword": ["=== [ソード] ===", "=== [ハンター] ==="],
        "weapon": ["=== [武器] ==="],
        "armor": ["=== [防具] ==="],
        "unit": ["=== [防具] ==="],
        "class": ["=== [クラス] ==="],
        "central city": ["=== [FrontPage] ===", "=== [リージョン] ==="],
        "aelio": ["=== [リージョン] ==="],
        "sega": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="],
        "update": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="],
        "event": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="]
    }
    
    priority_headers = []
    for key, headers in category_map.items():
        if key in lowered:
            priority_headers.extend(headers)

    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Split the file cleanly by structural section headers
            sections = content.split("=== [")
            
            for section in sections:
                if not section.strip():
                    continue
                
                # Reconstruct full header string context
                full_section_text = "=== [" + section
                
                # Check for explicit priority rule matching or keyword presence
                is_priority = any(p_head in full_section_text for p_head in priority_headers)
                
                # Check if specific terms match words inside the block body context
                words = [w for w in lowered.split() if len(w) > 3]
                matches_body = any(w in section.lower() for w in words) if words else False
                
                if is_priority or matches_body:
                    # Give the model a healthy chunk size (up to 4800 characters) so lists remain complete
                    extracted.append(full_section_text[:4800])
                
                if len(extracted) >= 4:  # Restrict array to avoid packing past Llama context limits
                    break
            
            # Always ensure seasonal live update visibility remains appended
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
            max_tokens=250,
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

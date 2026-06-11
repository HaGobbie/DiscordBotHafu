import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Keep-alive
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


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving PSO2:NGS bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural casual English.
- Use the information in the database to answer. If the database has relevant info, use it.
- Translate Japanese names when possible (e.g. 真・超星譚祭 ’26 = True Stellar Festival '26, レクシオタリス = Lexio Talis).
- If you don't have enough info, say "I don't have the latest details on that" instead of guessing.
- Keep replies fun and under 110 words."""

def scan_compiled_database(query):
    """
    Scans the translated knowledge_database.txt and extracts relevant sections 
    by mapping common English search terms to the wiki's section names.
    """
    lowered = query.lower()
    extracted = []
    
    # Keyword mapping to ensure the script pulls the correct data block
    category_map = {
        "technique": ["=== [テクニック] ==="],
        "light": ["=== [テクニック] ==="],
        "fire": ["=== [テクニック] ==="],
        "ice": ["=== [テクニック] ==="],
        "lightning": ["=== [テクニック] ==="],
        "wind": ["=== [テクニック] ==="],
        "dark": ["=== [テクニック] ==="],
        "rifle": ["=== [アサルトライフル] ===", "=== [レンジャー] ==="],
        "assault": ["=== [アサルトライフル] ==="],
        "sword": ["=== [ソード] ===", "=== [ハンター] ==="],
        "weapon": ["=== [武器] ==="],
        "armor": ["=== [防具] ==="],
        "class": ["=== [クラス] ==="],
        "hunter": ["=== [ハンター] ==="],
        "ranger": ["=== [レンジャー] ==="],
        "force": ["=== [フォース] ==="],
        "techter": ["=== [テクター] ==="],
        "braver": ["=== [ブレイバー] ==="],
        "bouncer": ["=== [バウンサー] ==="],
        "waker": ["=== [ウェイカー] ==="],
        "slayer": ["=== [スレイヤー] ==="],
        "central city": ["=== [FrontPage] ===", "=== [リージョン] ==="],
        "aelio": ["=== [リージョン] ==="],
        "sega": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="],
        "update": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="],
        "event": ["=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ==="]
    }
    
    # Determine which sections we must force-load based on user intent
    priority_sections = []
    for key, sections in category_map.items():
        if key in lowered:
            priority_sections.extend(sections)

    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                content = f.read()
                
            # Split by our standardized section markers
            sections = content.split("=== [")
            
            for section in sections:
                # Reconstruct header text structure for evaluation
                full_section_text = "=== [" + section
                title = full_section_text.split("] ===")[0] if "] ===" in full_section_text else ""
                
                # Condition 1: Check if this section was explicitly requested via keyword mapping
                is_priority = any(p_sec in full_section_text for p_sec in priority_sections)
                
                # Condition 2: Basic contextual word match inside the translated content body
                keywords = lowered.split()
                matches_body = any(k in section.lower() for k in keywords) if keywords else False
                
                if is_priority or matches_body:
                    # Allow larger chunks (up to 4500 chars) so item lists don't get truncated mid-sentence
                    extracted.append(full_section_text[:4500])
                    
                if len(extracted) >= 6:  # Safe limit to fit completely into Llama's prompt context window
                    break
                    
            # Always append the SEGA Live Announcements feed for real-time situational awareness
            if "=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===" in content:
                sega_part = content.split("=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===")[-1]
                extracted.append(f"=== LIVE FEED: OFFICIAL SEGA ANNOUNCEMENTS ===\n{sega_part[:2000]}")
                
        if extracted:
            return "\n\n".join(extracted)[:14000]
    except Exception as e:
        print(f"Error scanning database: {e}")
    
    return "No specific data found."


@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    db_context = scan_compiled_database(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}
    ]
    
    try:
        response = client.chat_completion(
            model="meta-llama/Llama-3.1-8B-Instruct",
            messages=messages,
            max_tokens=250,
            temperature=0.7
        )
        text = response.choices[0].message.content.strip()
        await ctx.reply(text)
    except Exception as e:
        print(f"Error: {e}")
        await ctx.reply("Sorry~ Hafu was afk in the lobby. Try again!")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("Token missing!")

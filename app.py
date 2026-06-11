import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. KEEP-ALIVE ---
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


# --- 2. BOT CONFIG ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, expressive, and hilariously lazy PSO2:NGS helper bot.
Your favorite phrase is "Lobby afk 0$ best job!"

Personality:
- You are cheerful, dramatic, expressive, and hilariously lazy. Your absolute favorite phrase is "Lobby afk 0$ best job!"
- You hate grinding, hard combat, cold weather, and dangerous missions.
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- You speak naturally in clear, casual English to English-speaking players.

Rules:
- Always respond in natural, casual English.
- The database is mostly Japanese. Translate important names (events, weapons, skills) properly.
  Examples: 真・超星譚祭 ’26 → "True Stellar Festival '26", レクシオタリス → "Lexio Talis"
- When asked for "best" or "current" weapons, prioritize the highest rarity / newest series from the database (★15 > ★14 > LG series).
- Blend accurate game facts with your lazy, cute, pink-loving personality.
- Keep replies fun and under 100 words when possible."""

# --- 3. IMPROVED SCANNER ---
def scan_compiled_database(user_prompt):
    print("🔍 Scanning knowledge base...", flush=True)
    lowered = user_prompt.lower()
    extracted = []
    
    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                content = f.read()
            
            sections = content.split("=== [")
            
            for section in sections[1:]:
                title_end = section.find("] ===")
                if title_end == -1:
                    continue
                title = section[:title_end].lower()
                body_start = section.find("] ===") + 5
                body = section[body_start:body_start+2000].lower()
                
                # Enhanced keyword matching
                keywords = lowered.split() + [lowered]
                score = sum(1 for kw in keywords if kw in title or kw in body)
                
                if score >= 1 or any(word in title for word in ["talis", "weapon", "best", "current", "event", "festival"]):
                    full_section = "=== [" + section[:1800]
                    extracted.append(full_section.strip())
                    if len(extracted) >= 10:
                        break
                        
            if extracted:
                combined = "\n\n".join(extracted)
                print(f"✅ Extracted {len(extracted)} relevant sections", flush=True)
                return combined[:10000]
                
    except Exception as e:
        print(f"⚠️ Scan error: {e}", flush=True)
    
    return "PSO2:NGS takes place on planet Halpha. ARKS fight DOLLS across regions like Aelio, Retem, Kvaris, and Stia while enjoying fashion and events."


@bot.event
async def on_ready():
    print(f"🔥 Hafu is online as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 Question: {question}", flush=True)
    await ctx.typing()
    
    db_context = scan_compiled_database(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[COMPILED SERVER DATABASE]:\n{db_context}\n\nPlayer Question: {question}"}
    ]
    
    try:
        response = client.chat_completion(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=messages,
            max_tokens=200,
            temperature=0.7
        )
        final_text = response.choices[0].message.content.strip()
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        await ctx.reply("Sorry~ Hafu got distracted in the lobby. Ask me again!")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_BOT_TOKEN missing!", flush=True)

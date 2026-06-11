import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. KEEP-ALIVE SERVER ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Hafu is alive and listening!")
    def log_message(self, format, *args):
        return 

def run_keep_alive_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 Keep-alive server online on port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


# --- 2. BOT CONFIGURATION ---
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

The [COMPILED SERVER DATABASE] is mostly in Japanese but contains very accurate game information.
- Translate and explain key terms naturally (weapon names, skills, story elements, etc.).
- Always blend real game facts from the database with your lazy, cute personality.
- Keep responses snappy, fun, and under 100 words when possible."""

# --- 3. IMPROVED DATABASE LOOKUP ---
def scan_compiled_database(user_prompt):
    print("🔍 Scanning enhanced knowledge base...", flush=True)
    lowered = user_prompt.lower()
    extracted = []
    
    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as f:
                content = f.read()
            
            # Split into sections for better relevance
            sections = content.split("=== [")
            
            for section in sections[1:]:  # Skip header
                title_end = section.find("] ===")
                if title_end == -1:
                    continue
                title = section[:title_end].lower()
                body = section[title_end:].lower()
                
                # Stronger keyword matching (Japanese + English)
                keywords = lowered.split() + [lowered]
                if any(kw in title or kw in body for kw in keywords):
                    # Take a clean chunk of the section
                    full_section = "=== [" + section[:1500]  # Limit size
                    extracted.append(full_section.strip())
                    if len(extracted) >= 8:  # Increased context
                        break
                        
            if extracted:
                combined = "\n\n".join(extracted)
                print(f"✅ Found relevant sections: {len(extracted)}", flush=True)
                return combined[:8000]  # Generous but safe limit
                
    except Exception as e:
        print(f"⚠️ Database scan error: {e}", flush=True)
    
    # Fallback
    return "PSO2:NGS is set on the planet Halpha. Players are ARKS fighting DOLLS while enjoying fashion, events, and exploration across regions like Aelio, Retem, Kvaris, and Stia."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has successfully logged in as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 Question received: {question}", flush=True)
    await ctx.typing()
    
    database_context = scan_compiled_database(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[COMPILED SERVER DATABASE]:\n{database_context}\n\nUser Question: {question}"}
    ]
    
    try:
        response = client.chat_completion(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=messages,
            max_tokens=180,
            temperature=0.75
        )
        final_text = response.choices[0].message.content
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ Inference error: {e}", flush=True)
        await ctx.reply("Sorry~ Hafu got a bit lazy and something went wrong. Try asking again!")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_BOT_TOKEN is missing!", flush=True)

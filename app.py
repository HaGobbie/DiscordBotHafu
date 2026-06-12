import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types
from google.genai.errors import APIError
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

# Global variable to hold the entire database text securely in RAM
FULL_DATABASE_TEXT = ""


# ==================== THE STRICT PERSONALITY SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving Phantasy Star Online 2: New Genesis (PSO2:NGS) bot.
Favorite line: "Lobby afk 0$ best job!"

Rules:
- Answer in natural, casual, and incredibly lazy English. Use emotes like *yawn* or *stretches lazily*.
- STRICT RULE: You MUST rely ONLY on the provided database context to answer the user's question. 
- Look thoroughly through all the text, tables, and sections provided. If the text genuinely lacks a clear, identifiable answer, do NOT invent fake names or information. Instead, maintain character and say something like: "*yawns* I'm too lazy to scroll through the data right now, maybe go look at the wiki yourself or ask someone in the lobby!"
- Keep your answers concise, accurate to the text provided, and true to the NGS universe.
"""


# ==================== DISCORD CORE COMMANDS ====================
@bot.event
async def on_ready():
    global FULL_DATABASE_TEXT
    
    # 1. Load the entire 1.5MB file into local memory once on startup
    if os.path.exists("knowledge_database.txt"):
        print("📂 Loading entire 1.5MB database into Render RAM...", flush=True)
        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            FULL_DATABASE_TEXT = f.read()
        print(f"✅ Database memory allocation successful! Characters read: {len(FULL_DATABASE_TEXT)}", flush=True)
    else:
        print("⚠️ Warning: knowledge_database.txt not found!", flush=True)

    # 2. Build the client connection objects for your 4 API projects
    for i, key in enumerate(GEMINI_KEYS):
        CLIENT_RING[i] = genai.Client(api_key=key)
        
    print(f"🔥 Hafu is online and fully configured with {len(GEMINI_KEYS)} keys!", flush=True)


@bot.command(name="ask")
async def ask(ctx, *, question: str):
    global current_key_index
    await ctx.typing()
    
    if not CLIENT_RING:
        await ctx.reply("Ah... *yawn* My brain keys aren't configured properly. Tell the admin~")
        return

    # Structure the message payload containing your full data asset alongside the prompt
    user_prompt = f"Database Content:\n{FULL_DATABASE_TEXT}\n\nUser Question: {question}"

    # Cycle through the key pool if a project encounters a 5 Requests Per Minute limit
    for attempt in range(len(GEMINI_KEYS)):
        idx = current_key_index
        client = CLIENT_RING.get(idx)
        
        try:
            response = client.models.generate_content(
                model=SELECTED_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.4,
                    max_output_tokens=1000
                )
            )
            
            try:
                finish_reason = response.candidates[0].finish_reason
                print(f"🔍 [Key {idx+1}] Finish Reason: {finish_reason} | Total Input Tokens processed dynamically: {response.usage_metadata.prompt_token_count}", flush=True)
            except Exception:
                pass

            text_out = response.text.strip()
            if not text_out:
                text_out = "*yawns* I read the whole data board but I'm too sleepy to summarize it..."
            
            await ctx.reply(text_out)
            return

        except APIError as api_err:
            if api_err.code == 429:
                print(f"⚠️ Project [{idx+1}] hit a rate limit window. Rotating index pointer to next project...", flush=True)
                current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
                continue 
            else:
                print(f"❌ API Error on Project [{idx+1}]: {api_err}", flush=True)
                await ctx.reply("*yawn* My head hurts... Something went wrong inside the database query.")
                return
        except Exception as e:
            print(f"❌ Unexpected Execution Error on Project [{idx+1}]: {e}", flush=True)
            await ctx.reply("Sorry~ Hafu got distracted by a butterfly. Try asking again!")
            return

    await ctx.reply("Ugh... *yawns loudly* The whole lobby is screaming at me at once! Give me a minute to rest, okay?~")


if __name__ == "__main__":
    DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: DISCORD_TOKEN environment variable is missing!")

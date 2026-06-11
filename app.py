import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- KEEP-ALIVE ---
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


# --- BOT CONFIG ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, phashion-obsessed PSO2:NGS helper bot.
Favorite phrase: "Lobby afk 0$ best job!"

CRITICAL RULES:
- Always respond in natural, casual English.
- Use ONLY information from the [COMPILED SERVER DATABASE]. Never make up weapon names, PA names, or technique names.
- Translate Japanese names properly (e.g. レクシオタリス = Lexio Talis, 真・超星譚祭 ’26 = True Stellar Festival '26, コウゲンセイ = Kougensei).
- For "best" or "current" weapons, choose the highest rarity shown (★15 or LG4).
- Keep replies fun, accurate, and under 110 words."""

# --- SCANNER ---
def scan_compiled_database(user_prompt):
    print("🔍 Scanning...", flush=True)
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
                body = section[title_end:].lower()[:3500]
                
                # Priority for key topics
                if any(x in lowered for x in ["talis", "best weapon", "weapon for"]):
                    if "タリス" in section or "talis" in title:
                        extracted.append("=== [" + section[:2600])
                        continue
                if any(x in lowered for x in ["photon art", "technique", "技", "テクニック"]):
                    if "テクニック" in section or "photon" in title:
                        extracted.append("=== [" + section[:2600])
                        continue
                if any(x in lowered for x in ["event", "festival", "current event"]):
                    if "超星譚祭" in section:
                        extracted.append("=== [" + section[:2600])
                        continue
                        
                # Normal keyword match
                keywords = lowered.split()
                if any(kw in title or kw in body for kw in keywords):
                    extracted.append("=== [" + section[:2300])
                    if len(extracted) >= 12:
                        break
                        
            if extracted:
                combined = "\n\n".join(extracted)
                print(f"✅ Pulled {len(extracted)} sections", flush=True)
                return combined[:14500]
                
    except Exception as e:
        print(f"Scan error: {e}", flush=True)
    
    return "No specific data found. Check the latest database for current weapons and events."


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
        {"role": "user", "content": f"[COMPILED SERVER DATABASE - Use ONLY this data. Do not hallucinate.]\n{db_context}\n\nPlayer Question: {question}"}
    ]
    
    try:
        response = client.chat_completion(
            model="Qwen/Qwen3-8B-Instruct",   # ← New model
            messages=messages,
            max_tokens=220,
            temperature=0.6
        )
        final_text = response.choices[0].message.content.strip()
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        await ctx.reply("Sorry~ Hafu was busy in the lobby. Ask me again!")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_BOT_TOKEN missing!", flush=True)

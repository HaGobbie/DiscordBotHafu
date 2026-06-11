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

Strict Rules:
- Respond in natural casual English only.
- Use ONLY information from the [COMPILED SERVER DATABASE]. Do not hallucinate weapon names or PA names.
- Translate Japanese terms accurately: レクシオタリス = Lexio Talis, 真・超星譚祭 ’26 = True Stellar Festival '26, コウゲンセイ = Kougensei.
- When asked for "best" weapon, look for ★15 or LG4 series in the database.
- Keep replies fun, accurate, and under 110 words."""

# --- STRONGER SCANNER ---
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
                body = section[title_end:].lower()[:3000]
                
                # Force pull relevant sections
                if any(word in lowered for word in ["talis", "weapon", "best", "current", "strongest"]):
                    if "talis" in title or "weapon" in title or "タリス" in section:
                        extracted.append("=== [" + section[:2200])
                        continue
                        
                if any(word in lowered for word in ["event", "festival", "current event"]):
                    if "超星譚祭" in section or "festival" in title:
                        extracted.append("=== [" + section[:2200])
                        continue
                        
                if any(word in lowered for word in ["technique", "photon art", "pa", "art"]):
                    if "テクニック" in section or "photon" in title:
                        extracted.append("=== [" + section[:2200])
                        continue
                        
                # Normal matching
                keywords = lowered.split()
                if any(kw in title or kw in body for kw in keywords):
                    extracted.append("=== [" + section[:2000])
                    if len(extracted) >= 12:
                        break
                        
            if extracted:
                combined = "\n\n".join(extracted)
                print(f"✅ Pulled {len(extracted)} sections", flush=True)
                return combined[:13000]
                
    except Exception as e:
        print(f"Scan error: {e}", flush=True)
    
    return "Current top weapons are from the Kougensei (★15) and Lexio series. Check the database for latest Talis recommendations."


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
            temperature=0.65
        )
        final_text = response.choices[0].message.content.strip()
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        await ctx.reply("Sorry~ Hafu was busy shopping for pink outfits. Try asking again!")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ DISCORD_BOT_TOKEN missing!", flush=True)

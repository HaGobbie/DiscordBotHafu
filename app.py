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

def scan_compiled_database(user_prompt):
    lowered = user_prompt.lower()
    extracted = []
    
    try:
        with open("knowledge_database.txt", "r", encoding="utf-8") as f:
            content = f.read()
        
        sections = content.split("=== [")
        
        for section in sections[1:]:
            title_end = section.find("] ===")
            if title_end == -1:
                continue
            title = section[:title_end].lower()
            body = section[title_end:].lower()[:3800]
            
            # Strong priority matching
            if any(x in lowered for x in ["event", "festival", "current event"]):
                if "超星譚祭" in section:
                    extracted.append("=== [" + section[:3000])
            if any(x in lowered for x in ["talis", "weapon", "best weapon"]):
                if "タリス" in section or "talis" in title:
                    extracted.append("=== [" + section[:3000])
            if any(x in lowered for x in ["photon art", "photon arts", "technique", "技"]):
                if "テクニック" in section or "sword" in title or "rifle" in title:
                    extracted.append("=== [" + section[:3000])
                    
            # General match
            if any(k in title or k in body for k in lowered.split()):
                extracted.append("=== [" + section[:2600])
                if len(extracted) >= 15:
                    break
                    
        if extracted:
            return "\n\n".join(extracted)[:15500]
    except:
        pass
    
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

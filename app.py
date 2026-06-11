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
    print(f"🌐 Keep-alive online", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are Hafu. You are helpful but very careful.
You ONLY use information from the provided database.
If you are not sure or the database doesn't clearly answer, say "I need to check the latest info" instead of guessing.
Translate Japanese names when possible.
Keep answers short and fun."""

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
            body = section[title_end:][:3000].lower()
            
            # Very aggressive for common questions
            if "talis" in lowered or "weapon" in lowered:
                if "タリス" in section or "talis" in title:
                    extracted.append("=== [" + section[:3000])
            if "event" in lowered or "festival" in lowered:
                if "超星譚祭" in section:
                    extracted.append("=== [" + section[:3000])
            if "technique" in lowered or "photon" in lowered or "技" in lowered:
                if "テクニック" in section:
                    extracted.append("=== [" + section[:3000])
                    
            if any(k in title or k in body for k in lowered.split()):
                extracted.append("=== [" + section[:2500])
                if len(extracted) >= 10:
                    break
                    
        if extracted:
            return "\n\n".join(extracted)[:14000]
    except:
        pass
    
    return "No clear data found for this question."


@bot.event
async def on_ready():
    print(f"🔥 Hafu is online!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    await ctx.typing()
    db_context = scan_compiled_database(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Database:\n{db_context}\n\nQuestion: {question}\nAnswer using only the database above."}
    ]
    
    try:
        response = client.chat_completion(
            model="meta-llama/Llama-3.1-8B-Instruct",
            messages=messages,
            max_tokens=250,
            temperature=0.5   # Lower = less creative
        )
        text = response.choices[0].message.content.strip()
        await ctx.reply(text)
    except Exception as e:
        print(f"Error: {e}")
        await ctx.reply("Sorry, something went wrong. Try again.")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("Token missing!")

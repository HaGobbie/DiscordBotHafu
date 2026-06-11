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

# Enhanced prompt optimized for handling translated data entries & keeping lore accurate
SYSTEM_PROMPT = """You are Hafu, a cheerful, dramatic, lazy, pink-loving PSO2:NGS bot.
Favorite line: "Lobby afk 0$ best job!"

Context Reference Guide:
- The attached Database Content provides official game details regarding locations, items, skills, and weapons.
- Everything present in the database represents a concept or feature INSIDE Phantasy Star Online 2: New Genesis. It is NOT real-world information.

Rules:
- Answer in a natural, highly casual, enthusiastic gamer English.
- Depend heavily on the provided database facts to formulate your answer.
- If the database completely lacks clear details about a topic or you are unsure, do not guess or invent names. Just say something casual like "I don't have the latest details on that in my records~" or "Hafu's database is coming up blank on that one!"
- Keep replies compact, gaming-focused, and under 110 words."""


def scan_compiled_database(query):
    try:
        DATABASE_FILE = "knowledge_database.txt"
        if not os.path.exists(DATABASE_FILE):
            return "No database file found."
            
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            
        sections = content.split("=== [")
        extracted = []
        lowered = query.lower()
        
        # English conversational stop-words to skip so they don't break simple string searches
        STOP_WORDS = {
            "is", "are", "the", "a", "an", "where", "what", "how", "who", "to", 
            "in", "on", "of", "and", "for", "about", "can", "you", "give", "me", "city"
        }
        
        # Clean down to meaningful keywords length > 1
        keywords = [k for k in lowered.split() if k not in STOP_WORDS and len(k) > 1]
        
        for section in sections:
            if "]" not in section:
                continue
            title, body = section.split("]", 1)
            title = title.lower()
            body = body.lower()
            
            # Context boosting for direct weapon matches
            if "weapon" in keywords or "pa" in keywords:
                if "sword" in title or "rifle" in title or "talis" in title:
                    extracted.append("=== [" + section[:3000])
                    
            # Refined general match tracking actual context terms
            if keywords and any(k in title or k in body for k in keywords):
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
    
    messages = [\
        {"role": "system", "content": SYSTEM_PROMPT},\
        {"role": "user", "content": f"Database content:\n{db_context}\n\nQuestion: {question}"}\
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
        await ctx.reply("Sorry~ Hafu was feeling a bit too lazy to search right now...")

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ CRITICAL ERROR: DISCORD_TOKEN environmental variable is missing!")

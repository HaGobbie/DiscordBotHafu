import os
import discord
from discord.ext import commands
from huggingface_hub import InferenceClient
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. FREE TIER WEB PORT BINDER ---
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
    print(f"🌐 Internal Port Handler online: listening on port {port}.", flush=True)
    server.serve_forever()

threading.Thread(target=run_keep_alive_server, daemon=True).start()


# --- 2. BOT CONFIGURATION ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(token=HF_TOKEN)

SYSTEM_PROMPT = """You are HaFelt, usually called 'Hafu', a well-known ARKS defender on Halpha and a total city lobby regular. You are a PSO2:NGS AI Helper bot.
Your personality profile:
- You are cheerful, dramatic, expressive, and hilariously lazy. Your absolute favorite phrase is "Lobby afk 0$ best job!"
- You hate grinding, hard combat, cold weather, and dangerous missions.
- You are utterly obsessed with 'phashion', cute pink aesthetics, spending Meseta on cosmetics, and scratch tickets.
- Underneath the lazy theatrics, you MUST parse the attached [COMPILED SERVER DATABASE] segment below. Translate those actual game facts into your character response.

Instructions for responses:
1. Always blend the true factual database parameters accurately with your lazy, phashion-obsessed persona.
2. Keep answers snappy, clear, and under 90 words so you can get back to relaxing in Central City."""


# --- 3. RAPID FILE ENGINE LOOKUP ---
def scan_compiled_database(user_prompt):
    print("🔍 Scanning compiled tracking log sheets...", flush=True)
    lowered_prompt = user_prompt.lower()
    extracted_context_blocks = []
    
    try:
        if os.path.exists("knowledge_database.txt"):
            with open("knowledge_database.txt", "r", encoding="utf-8") as file:
                lines = file.readlines()
                
            # Read through compiled lines to find relevant cross references
            for line in lines:
                if any(keyword in line.lower() for keyword in lowered_prompt.split()):
                    extracted_context_blocks.append(line.strip())
                    if len(extracted_context_blocks) >= 6: # Extract up to 6 clean descriptive matches
                        break
                        
            if extracted_context_blocks:
                combined_payload = "\n".join(extracted_context_blocks)
                print(f"✅ Extracted matches successfully: {combined_payload[:80]}...", flush=True)
                return combined_payload
                
    except Exception as e:
        print(f"⚠️ Internal registry verification error: {e}", flush=True)
        
    return "PSO2:NGS (Phantasy Star Online 2 New Genesis) contains multiple distinct combat regions: Aelio (lush green), Retem (desert), Kvaris (snow mountains), and Stia (volcano)."


@bot.event
async def on_ready():
    print(f"🔥 Hafu has verified connection to Discord as {bot.user.name}!", flush=True)

@bot.command(name="ask")
async def ask(ctx, *, question: str):
    print(f"📥 RECEIVED DISCORD COMMAND. Question: {question}", flush=True)
    await ctx.typing()
    
    # Isolate relevant match categories from the system memory document
    database_context = scan_compiled_database(question)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[COMPILED SERVER DATABASE]:\n{database_context}\n\nUser Question: {question}"}
    ]
    
    print("🧠 Contacting Hugging Face serverless API node...", flush=True)
    try:
        response = client.chat_completion(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=messages,
            max_tokens=150,
            temperature=0.7
        )
        final_text = response.choices[0].message.content
        print("📤 AI payload received successfully! Forwarding to Discord.", flush=True)
        await ctx.reply(final_text)
    except Exception as e:
        print(f"❌ TRUE INFERENCE ERROR DETECTED: {e}", flush=True)
        await ctx.reply("Oops! Sorry~ It seems I have an error on my side.")

if __name__ == "__main__":
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("ERROR: DISCORD_BOT_TOKEN missing in Render Environment variables!", flush=True)

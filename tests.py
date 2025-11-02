import os
from dotenv import load_dotenv

load_dotenv()
print("DISCORD_TOKEN:", os.getenv("DISCORD_TOKEN"))

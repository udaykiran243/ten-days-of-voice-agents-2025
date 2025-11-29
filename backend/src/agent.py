import logging
import json
import random
import asyncio
import os
from typing import Annotated, Literal, List

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    function_tool,
    RunContext
)
from livekit.plugins import murf, deepgram, google, silero
from livekit import rtc

load_dotenv(".env.local")
logger = logging.getLogger("game-master")

# --- CONFIGURATION ---
# This ensures files are saved exactly where agent.py is located (backend/src)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 1. Game State Engine ---
class GameState:
    def __init__(self):
        self.data = {
            "player": {
                "hp": 100,
                "max_hp": 100,
                "ram": 80, 
                "max_ram": 100,
                "status": "Healthy",
                "inventory": ["Cyberdeck", "10mm Pistol", "Stimpack"]
            },
            "world": {
                "location": "Neo-Veridia - Dumpster Behind Arasaka",
                "danger_level": "Mildly Annoying",
                "weather": "Acid Rain (Again)"
            },
            "log": [] 
        }

    def load_from_json(self, json_data: dict):
        self.data = json_data

    def update_stats(self, hp_delta: int = 0, ram_delta: int = 0):
        p = self.data["player"]
        p["hp"] = max(0, min(p["max_hp"], p["hp"] + hp_delta))
        p["ram"] = max(0, min(p["max_ram"], p["ram"] + ram_delta))
        
        if p["hp"] <= 0: p["status"] = "FLATLINED"
        elif p["hp"] < 40: p["status"] = "Not Great"
        elif p["hp"] < 80: p["status"] = "Bruised"
        else: p["status"] = "Healthy"

    def modify_inventory(self, item: str, action: str):
        inv = self.data["player"]["inventory"]
        if action == "add":
            inv.append(item)
        elif action == "remove" and item in inv:
            inv.remove(item)

    def add_log(self, message: str):
        self.data["log"].append(message)
        if len(self.data["log"]) > 5:
            self.data["log"].pop(0)

    def to_json(self):
        return json.dumps(self.data)

# --- 2. The Game Master Agent ---
class GameMaster(Agent):
    def __init__(self, room):
        super().__init__(
            instructions="""
            You are 'The Glitch', a chaotic and humorous Game Master for a Cyberpunk RPG.
            
            SETTING:
            - Neo-Veridia City (it smells like ozone and cheap noodles).
            - Player is a "Runner" (a mercenary hacker trying to look cool).
            - Mission: Break into Arasaka Tower without tripping over your own feet.
            
            MECHANICS:
            Action Resolution: Call `perform_check` for risky actions.
            Inventory: Call `manage_inventory` for items.
            
            STYLE:
            - Tone: Humorous, Sarcastic, Witty.
            - Poke fun at the player if they roll low (e.g., "Nice try, hero.").
            - Celebrate high rolls with over-the-top enthusiasm (e.g., "YOU ARE A GOD OF THE NET!").
            - Break the fourth wall slightly.
            - KEEP IT FAST. Describe the scene, then ask "What do you do?"
            """
        )
        self.game = GameState()
        self.room = room

    async def sync_ui(self):
        try:
            await self.room.local_participant.publish_data(
                self.game.to_json(),
                topic="game_state_update"
            )
        except Exception as e:
            logger.warning(f"UI Sync failed: {e}")

    @function_tool
    async def perform_check(
        self, 
        ctx: RunContext, 
        action: Annotated[str, "Description"],
        difficulty: Annotated[int, "DC"] = 12,
        risk_damage: Annotated[int, "Damage if fail"] = 0
    ):
        roll = random.randint(1, 20)
        outcome = "FAILURE"
        damage_taken = 0
        
        if roll == 20:
            outcome = "CRITICAL SUCCESS"
            self.game.update_stats(ram_change=10)
        elif roll >= difficulty:
            outcome = "SUCCESS"
        elif roll == 1:
            outcome = "CRITICAL FAILURE"
            damage_taken = risk_damage * 2
        else:
            outcome = "FAILURE"
            damage_taken = risk_damage

        if damage_taken > 0:
            self.game.update_stats(hp_delta=-damage_taken)
        
        log_msg = f"{action} | Roll: {roll} vs DC{difficulty} | {outcome}"
        self.game.add_log(log_msg)
        await self.sync_ui()
        
        # The prompt here encourages the LLM to be funny about the result
        return f"Result: {outcome} (Roll {roll}). Damage Taken: {damage_taken}. Current HP: {self.game.data['player']['hp']}. Narrate this with humor/sarcasm."

    @function_tool
    async def manage_inventory(
        self,
        ctx: RunContext,
        item: Annotated[str, "Item name"],
        action: Annotated[Literal["add", "remove"], "Action"]
    ):
        self.game.modify_inventory(item, action)
        self.game.add_log(f"Inventory: {action.upper()} {item}")
        await self.sync_ui()
        return f"Inventory updated: {self.game.data['player']['inventory']}"

# --- 3. Entrypoint ---

def prewarm(proc: JobProcess):
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except:
        proc.userdata["vad"] = silero.VAD.load(use_onnx=False)

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()

    vad = ctx.proc.userdata["vad"]
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-natalie", # Reverted to Matthew as a safe fallback for unavailable voices
            style="Promo",       # Energetic style
            text_pacing=True
        ),
        vad=vad,
    )

    agent = GameMaster(room=ctx.room)
    
    # --- DATA PACKET HANDLER ---
    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        try:
            payload = json.loads(data.data.decode('utf-8'))
            
            if payload.get("type") == "SAVE_REQ":
                save_path = os.path.join(SCRIPT_DIR, "savegame.json")
                logger.info(f"Saving game state to: {save_path}")
                
                with open(save_path, "w") as f:
                    json.dump(agent.game.data, f, indent=2)
                
                msg = json.dumps({"type": "SYSTEM_MSG", "message": f"Game saved to {save_path}"})
                asyncio.create_task(ctx.room.local_participant.publish_data(msg, topic="system"))
                
            elif payload.get("type") == "LOAD_REQ":
                new_state = payload.get("state")
                if new_state:
                    agent.game.load_from_json(new_state)
                    agent.game.add_log("SYSTEM: GAME LOADED.")
                    asyncio.create_task(agent.sync_ui())
                    asyncio.create_task(session.say("Whoa, déjà vu. Reloading reality... okay, where were we?", allow_interruptions=True))

        except Exception as e:
            logger.error(f"Data error: {e}")

    await session.start(agent=agent, room=ctx.room)
    await agent.sync_ui()
    await session.say("System online. Welcome to Neo-Veridia, chummer. It's raining acid, your rent is due, and you're standing outside Arasaka Tower. Don't mess this up. What do you do?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
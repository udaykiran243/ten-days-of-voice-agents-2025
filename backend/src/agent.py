import logging
import json
import os
from datetime import datetime
from typing import Annotated, List

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    tokenize,
    function_tool,
    RunContext
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# --- CONFIGURATION: ROBUST PATHS ---
# Get the actual folder where this script (agent.py) is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Create the data folder specifically inside that directory
DATA_FOLDER = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_FOLDER, exist_ok=True)

logger.info(f"Saving data to: {DATA_FOLDER}")

# --- 1. Wellness Journal (Memory & Analytics) ---
class WellnessJournal:
    def __init__(self, filename="wellness_log.json"):
        self.filepath = os.path.join(DATA_FOLDER, filename)
        self._ensure_file_healthy()

    def _ensure_file_healthy(self):
        """Creates file if missing, or resets it if corrupt/empty."""
        should_reset = False
        
        if not os.path.exists(self.filepath):
            should_reset = True
        elif os.path.getsize(self.filepath) == 0:
            should_reset = True
        else:
            # Validate JSON content
            try:
                with open(self.filepath, "r") as f:
                    json.load(f)
            except (json.JSONDecodeError, Exception):
                logger.warning(f"Corrupt journal found at {self.filepath}. Resetting.")
                should_reset = True

        if should_reset:
            with open(self.filepath, "w") as f:
                json.dump([], f)

    def get_last_entry(self):
        """Retrieves the most recent check-in for context."""
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                if data and isinstance(data, list) and len(data) > 0:
                    return data[-1]
        except Exception as e:
            logger.error(f"Error reading journal: {e}")
            # Attempt to auto-heal if read fails
            self._ensure_file_healthy()
            return None
        return None

    def log_entry(self, mood_text: str, mood_score: int, goals: List[str], summary: str):
        """Appends a new entry to the log."""
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mood_text": mood_text,
            "mood_score": mood_score,
            "goals": goals,
            "summary": summary
        }
        
        # Safer Read-Modify-Write pattern
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                if not isinstance(data, list): data = []
        except (FileNotFoundError, json.JSONDecodeError):
            data = []

        data.append(entry)

        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        return entry

    def get_weekly_stats(self):
        """Advanced Goal 2: Weekly Reflection Logic"""
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            
            if not data:
                return "No records found."

            recent_entries = data[-7:]
            scores = [e.get('mood_score', 5) for e in recent_entries]
            avg_score = sum(scores) / len(scores) if scores else 0
            total_goals = sum(len(e.get('goals', [])) for e in recent_entries)
            
            return {
                "entries_count": len(recent_entries),
                "average_mood_score": round(avg_score, 1),
                "total_goals_set": total_goals,
                "mood_trend": "Improving" if len(scores) > 1 and scores[-1] >= scores[0] else "Fluctuating"
            }
        except Exception as e:
            return f"Error calculating stats: {str(e)}"

# --- 2. Task Manager (Advanced Goal 1) ---
class TaskJournal:
    def __init__(self, filename="tasks.json"):
        self.filepath = os.path.join(DATA_FOLDER, filename)
        self._ensure_file_healthy()

    def _ensure_file_healthy(self):
        should_reset = False
        if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
            should_reset = True
        else:
            try:
                with open(self.filepath, "r") as f:
                    json.load(f)
            except json.JSONDecodeError:
                should_reset = True
        
        if should_reset:
            with open(self.filepath, "w") as f:
                json.dump([], f)

    def add_task(self, task_desc: str, due_date: str = "Today"):
        new_task = {
            "task": task_desc,
            "due": due_date,
            "status": "Pending",
            "created_at": datetime.now().strftime("%Y-%m-%d")
        }
        
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                if not isinstance(data, list): data = []
        except (FileNotFoundError, json.JSONDecodeError):
            data = []

        data.append(new_task)

        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
            
        return new_task

# --- 3. The Advanced Wellness Agent ---
class WellnessCompanion(Agent):
    def __init__(self, context_str: str) -> None:
        super().__init__(
            instructions=f"""
            You are a supportive Health & Wellness Voice Companion.
            
            CONTEXT FROM HISTORY:
            {context_str}
            
            YOUR CAPABILITIES:
            1. Daily Check-in: Ask about Mood (Text AND Score 1-10) and Goals.
            2. Task Management: If the user mentions a specific task (e.g., "I need to email my boss"), OFFER to save it to their task list.
            3. Weekly Reflection: If the user asks "How has my week been?", use the `get_weekly_insights` tool.

            FLOW:
            - Greet & Check Context.
            - Ask: "How are you feeling 1-10?" and "What is your main goal?"
            - If they mention a task -> Ask "Should I add that to your task list?" -> Call `create_task`.
            - Recap & Save: Call `save_checkin` at the end.
            """,
        )
        self.wellness_journal = WellnessJournal()
        self.task_journal = TaskJournal()

    @function_tool
    async def save_checkin(
        self, 
        ctx: RunContext, 
        mood_text: Annotated[str, "User's verbal description of mood"],
        mood_score: Annotated[int, "User's mood score from 1-10"],
        goals: Annotated[List[str], "List of goals for the day"],
        summary: Annotated[str, "Brief summary of the chat"]
    ):
        """Save the daily check-in data."""
        entry = self.wellness_journal.log_entry(mood_text, mood_score, goals, summary)
        return f"Saved check-in. Mood: {mood_score}/10."

    @function_tool
    async def create_task(
        self,
        ctx: RunContext,
        task_description: Annotated[str, "The specific task to do"],
        due_when: Annotated[str, "When it should be done (e.g. 'Today', 'Tomorrow')"] = "Today"
    ):
        """Add a specific item to the user's Todo list file."""
        try:
            task = self.task_journal.add_task(task_description, due_when)
            return f"Task created: '{task_description}' for {due_when}."
        except Exception as e:
            return f"Failed to create task: {e}"

    @function_tool
    async def get_weekly_insights(self, ctx: RunContext):
        """Call this if the user asks for a summary of their week or mood trends."""
        stats = self.wellness_journal.get_weekly_stats()
        return f"Weekly Stats: {stats}"

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Load Context
    journal = WellnessJournal()
    last = journal.get_last_entry()
    
    history_context = "No previous history."
    if last:
        history_context = (
            f"Last Session: {last.get('timestamp')}\n"
            f"Last Mood: {last.get('mood_score')}/10 ({last.get('mood_text')})\n"
            f"Last Goals: {', '.join(last.get('goals', []))}"
        )

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew", 
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
    )

    agent = WellnessCompanion(context_str=history_context)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
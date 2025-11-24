import logging
import json
import os
from typing import Annotated, Optional, Literal

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    tokenize,
    function_tool,
    RunContext
)
from livekit.plugins import murf, deepgram, google, silero

load_dotenv(".env.local")
logger = logging.getLogger("tutor-agent")

# --- 1. Load Content ---
CONTENT_FILE = "day4_tutor_content.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FULL_PATH = os.path.join(SCRIPT_DIR, CONTENT_FILE)

COURSE_CONTENT = []
if os.path.exists(FULL_PATH):
    with open(FULL_PATH, "r") as f:
        COURSE_CONTENT = json.load(f)
else:
    logger.warning(f"Content file not found at {FULL_PATH}.")

# --- 2. The Tutor Agent ---
class TutorAgent(Agent):
    def __init__(self, session: AgentSession):
        super().__init__(
            instructions="""
            You are the 'Active Recall Coach'. 
            Your goal is to welcome the user and ask them what topic they want to study today.
            
            AVAILABLE TOPICS: Variables, Loops, Functions.
            
            Once they pick a topic, ask if they want to start with:
            1. LEARN Mode (I explain it)
            2. QUIZ Mode (I test you)
            3. TEACH-BACK Mode (You explain it to me)
            
            Use the `set_study_mode` tool immediately once they decide.
            """,
        )
        self.agent_session = session
        self.current_topic_id = None

    @function_tool
    async def set_study_mode(
        self,
        ctx: RunContext,
        mode: Annotated[Literal["learn", "quiz", "teach_back"], "The mode to switch to"],
        topic_name: Annotated[Optional[str], "The topic to study"] = None
    ):
        """Switch the learning mode and/or topic. This changes the agent's personality and voice."""
        
        # 1. Resolve Topic
        if topic_name:
            found = next((t for t in COURSE_CONTENT if t["title"].lower() in topic_name.lower()), None)
            if found: self.current_topic_id = found["id"]
        
        # Get Topic Data
        topic_data = next((t for t in COURSE_CONTENT if t["id"] == self.current_topic_id), None)
        if not topic_data:
            return "Please select a valid topic first (Variables, Loops, Functions)."

        # 2. Configure Voice & Persona based on Mode
        voice_id = "en-US-matthew" # Default
        new_instructions = ""

        if mode == "learn":
            voice_id = "en-US-matthew" # Tutor
            new_instructions = f"""
            Your New Role: Tutor (Voice: Matthew).
            MODE: LEARN
            TOPIC: {topic_data['title']}
            CONTENT: {topic_data['summary']}
            GOAL: Explain the concept clearly using the content above. Be concise. Then ask if they are ready for a Quiz.
            """
        elif mode == "quiz":
            voice_id = "en-US-alicia" # Quiz Master
            new_instructions = f"""
            Your New Role: Quiz Master (Voice: Alicia).
            MODE: QUIZ
            TOPIC: {topic_data['title']}
            SAMPLE QUESTION: {topic_data['sample_question']}
            GOAL: Ask the sample question. If they answer correctly, ask a harder follow-up. If wrong, give a hint.
            """
        elif mode == "teach_back":
            voice_id = "en-US-ken" # Evaluator
            new_instructions = f"""
            Your New Role: Evaluator (Voice: Ken).
            MODE: TEACH-BACK
            TOPIC: {topic_data['title']}
            REFERENCE: {topic_data['summary']}
            GOAL: Ask the user to teach YOU. Listen, then give a score (0-100) based on accuracy compared to the reference.
            """

        # 3. Apply Changes
        
        # Update Voice (Hot-Swap)
        logger.info(f"Switching voice to {voice_id}")
        self.agent_session.tts = murf.TTS(
            voice=voice_id,
            style="Conversation",
            text_pacing=True
        )

        # Return the new instructions as the tool output. 
        # The LLM will see this immediately and adopt the new persona.
        return f"""
        SYSTEM UPDATE: 
        - Voice switched to {voice_id}.
        - Mode switched to {mode.upper()}.
        
        INSTRUCTIONS FOR NEXT RESPONSE:
        {new_instructions}
        
        (Start speaking as the new persona now.)
        """

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()

    # Initialize Session with Default Voice (Matthew)
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-matthew", style="Conversation", text_pacing=True),
        vad=ctx.proc.userdata["vad"],
    )

    # Initialize Agent
    agent = TutorAgent(session=session)

    await session.start(
        agent=agent,
        room=ctx.room
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
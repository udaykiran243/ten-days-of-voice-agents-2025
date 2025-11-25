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
    function_tool,
    RunContext
)
from livekit.agents import tts as lk_tts
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

# --- 2. Dynamic Voice Wrapper ---
class DynamicMurfTTS(lk_tts.TTS):
    def __init__(self, initial_voice="en-US-matthew"):
        super().__init__(
            capabilities=lk_tts.TTSCapabilities(streaming=True), 
            sample_rate=44100, 
            num_channels=1
        )
        self._current_engine = murf.TTS(voice=initial_voice, style="Conversation", text_pacing=True)

    def set_voice(self, voice_id: str):
        if self._current_engine._opts.voice != voice_id:
            logger.info(f"DynamicMurfTTS switching to: {voice_id}")
            self._current_engine = murf.TTS(voice=voice_id, style="Conversation", text_pacing=True)

    def synthesize(self, text: str):
        return self._current_engine.synthesize(text)

    def stream(self, **kwargs): 
        return self._current_engine.stream(**kwargs)

# --- 3. Configuration Helper ---
def get_mode_config(mode: str, topic_id: str):
    topic_data = next((t for t in COURSE_CONTENT if t["id"] == topic_id), None)
    topic_title = topic_data["title"] if topic_data else "General"
    
    if mode == "learn":
        return {
            "voice": "en-US-matthew",
            "instructions": f"""
                *** SYSTEM UPDATE: You are now the TUTOR (Voice: Matthew). ***
                
                MODE: LEARN
                TOPIC: {topic_title}
                CONTENT: {topic_data['summary'] if topic_data else 'No content found.'}
                
                INSTRUCTIONS: Explain the concept clearly using the content above. Be concise. 
                After explaining, ask: "Ready for a Quiz?"
            """
        }
    elif mode == "quiz":
        return {
            "voice": "en-US-alicia",
            "instructions": f"""
                *** SYSTEM UPDATE: You are now the QUIZ MASTER (Voice: Alicia). ***
                
                MODE: QUIZ
                TOPIC: {topic_title}
                SAMPLE QUESTION: {topic_data['sample_question'] if topic_data else 'No question found.'}
                
                INSTRUCTIONS: Ask the sample question immediately.
                - If they answer correctly, congratulate them energetically.
                - If wrong, give a gentle hint.
                After 2 questions, suggest TEACH-BACK Mode.
            """
        }
    elif mode == "teach_back":
        return {
            "voice": "en-US-ken",
            "instructions": f"""
                *** SYSTEM UPDATE: You are now the EVALUATOR (Voice: Ken). ***
                
                MODE: TEACH-BACK
                TOPIC: {topic_title}
                REFERENCE SUMMARY: {topic_data['summary'] if topic_data else ''}
                
                INSTRUCTIONS: Say "Okay, you're the teacher now. Explain {topic_title} to me."
                Listen, then score them (0-100) and give feedback.
            """
        }
    return {"voice": "en-US-matthew", "instructions": "You are a helpful assistant."}

# --- 4. The Tutor Agent ---
class TutorAgent(Agent):
    def __init__(self, session: AgentSession):
        super().__init__(
            instructions="""
            You are the 'Active Recall Coach'. 
            Your goal is to welcome the user and ask them what topic they want to study today.
            
            AVAILABLE TOPICS: Variables, Loops, Functions.
            
            Once they pick a topic, ask if they want to start with:
            1. LEARN Mode
            2. QUIZ Mode
            3. TEACH-BACK Mode
            
            Use the `set_study_mode` tool immediately once they decide.
            IMPORTANT: Do not say "I cannot change my voice". The `set_study_mode` tool WILL change your voice automatically.
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
        """Switch learning mode/topic. Triggers voice change and persona update."""
        
        # 1. Update State
        if topic_name:
            found = next((t for t in COURSE_CONTENT if t["title"].lower() in topic_name.lower()), None)
            if found: self.current_topic_id = found["id"]
        
        if not self.current_topic_id:
            return "Please ask the user to select a valid topic first."

        # 2. Get Config
        config = get_mode_config(mode, self.current_topic_id)
        
        # 3. EXECUTE THE VOICE SWITCH (Directly on the wrapper)
        if isinstance(self.agent_session.tts, DynamicMurfTTS):
            logger.info(f"Tool executing voice switch to {config['voice']}")
            self.agent_session.tts.set_voice(config['voice'])
        
        # 4. Return New Persona Instructions
        return f"""
        SUCCESS: Voice switched to {config['voice']}.
        
        {config['instructions']}
        
        (Adopt this new persona immediately.)
        """

# --- 5. Entrypoint ---

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()

    # Initialize Session with Dynamic TTS
    dynamic_tts = DynamicMurfTTS(initial_voice="en-US-matthew")

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=dynamic_tts, 
        vad=ctx.proc.userdata["vad"],
    )

    # Pass session to agent so tools can access TTS
    agent = TutorAgent(session=session)

    await session.start(agent=agent, room=ctx.room)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
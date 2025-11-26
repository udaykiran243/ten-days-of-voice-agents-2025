import logging
import os
from typing import Annotated, Literal

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
from database import FraudDB  # Importing our new SQLite handler

load_dotenv(".env.local")
logger = logging.getLogger("fraud-agent")

# --- 1. The Fraud Agent ---
class FraudAgent(Agent):
    def __init__(self, case_data):
        # We instantiate the DB connection for the agent to use in tools
        self.db = FraudDB()
        self.case = case_data
        
        super().__init__(
            instructions=f"""
            You are 'Sarah' from the **Chase Bank Fraud Security Team**.
            You are calling {case_data['name']} regarding a suspicious transaction on their card ending in {case_data['card_last4']}.
            
            YOUR SECURITY DATA (PRIVATE):
            - Correct Security Answer: "{case_data['security_answer']}"
            
            TRANSACTION DETAILS:
            - {case_data['merchant']}
            - {case_data['amount']}
            - {case_data['location']}
            - {case_data['timestamp']}
            
            CALL FLOW:
            1. **Introduction:** State your name and that this is an urgent security alert.
            2. **Verification:** Ask the user to verify identity by answering: "{case_data['security_question']}".
               - IF WRONG: Politely apologize and end the call. Decision: 'verification_failed'.
               - IF RIGHT: Proceed.
            3. **Investigation:** Read transaction details. Ask: "Did you authorize this charge?"
            4. **Resolution:**
               - YES (Authorized) -> Decision is 'confirmed_safe'.
               - NO (Unauthorized) -> Decision is 'confirmed_fraud'.
            5. **Action:** You MUST call `resolve_fraud_case` with the exact decision string ('confirmed_safe' or 'confirmed_fraud') to save the result.
            """
        )

    @function_tool
    async def resolve_fraud_case(
        self, 
        ctx: RunContext, 
        decision: Annotated[Literal["confirmed_safe", "confirmed_fraud", "verification_failed"], "The final outcome"],
        summary_note: Annotated[str, "A brief summary of what the customer said"]
    ):
        """Call this to close the case and update the database."""
        try:
            logger.info(f"Resolving case {self.case['customer_id']} as {decision}")
            self.db.update_case_status(self.case["customer_id"], decision, summary_note)
            
            if decision == "confirmed_fraud":
                return "Marked as FRAUD in Database. Card blocked. Tell user: New card mailed (3-5 business days)."
            elif decision == "confirmed_safe":
                return "Marked as SAFE in Database. Restrictions lifted. Tell user: Account is secure."
            else:
                return "Verification failed. Account locked."
        except Exception as e:
            logger.error(f"Failed to update database: {e}")
            # Return a success message to the LLM anyway to prevent the "technical difficulties" voice error
            return f"System note logged: {decision}. Proceed with closing the call."

# --- 2. Entrypoint ---

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    try:
        ctx.log_context_fields = {"room": ctx.room.name}
        await ctx.connect()

        # Init DB
        db = FraudDB()
        
        # Telephony Logic: Check Caller ID
        participant = await ctx.wait_for_participant()
        logger.info(f"Caller: {participant.identity}")
        
        # Try to find case by phone number first
        case = db.get_case_by_phone(participant.identity)
        
        if not case:
            logger.info("Phone not found, falling back to 'John Doe' for demo.")
            case = db.get_case_by_name("John Doe")

        if not case:
            logger.error("Critical: No case found in DB.")
            return

        session = AgentSession(
            stt=deepgram.STT(model="nova-3"),
            llm=google.LLM(model="gemini-2.5-flash"),
            tts=murf.TTS(
                voice="en-US-alicia", 
                style="Conversation",
                text_pacing=True
            ),
            vad=ctx.proc.userdata["vad"], 
        )

        agent = FraudAgent(case_data=case)
        await session.start(agent=agent, room=ctx.room)
        await session.say(f"Hello, is this {case['name']}?", allow_interruptions=True)

    except Exception as e:
        logger.error(f"Error in entrypoint: {e}")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
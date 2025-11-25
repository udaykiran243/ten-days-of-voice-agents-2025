import logging
import json
import os
from datetime import datetime
from typing import Annotated, Optional

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

load_dotenv(".env.local")
logger = logging.getLogger("sdr-agent")

# --- 1. Paths ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "company_data.json")
LEADS_DIR = os.path.join(SCRIPT_DIR, "leads")
os.makedirs(LEADS_DIR, exist_ok=True)

# --- 2. Lead Management ---
class LeadForm:
    def __init__(self):
        self.data = {
            "name": None, "company": None, "role": None,
            "use_case": None, "team_size": None,
            "timeline": None, "email": None
        }
    
    def update(self, field, value):
        if field in self.data:
            self.data[field] = value
            return True
        return False

    def save_to_file(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = (self.data['name'] or "unknown").replace(" ", "_")
        filename = f"lead_{safe_name}_{timestamp}.json"
        filepath = os.path.join(LEADS_DIR, filename)
        with open(filepath, "w") as f:
            json.dump(self.data, f, indent=2)
        return filename

# --- 3. The Agent ---
class SDRAgent(Agent):
    def __init__(self, company_data):
        super().__init__(
            instructions=f"""
            You are Rohan, an SDR for **Razorpay**.
            GOAL: Qualify the lead (Name, Company, Role, Use Case, Team Size, Timeline) and answer questions.
            
            - Use `lookup_info` for Pricing/Products.
            - Use `update_lead` to save details.
            - Use `finalize_call` when the user is done.
            
            If asked about pricing/charges, ALWAYS check the tool first.
            """
        )
        self.lead_form = LeadForm()
        self.company_data = company_data

    @function_tool
    async def lookup_info(
        self, 
        ctx: RunContext, 
        query: Annotated[str, "Topic (pricing, products, etc)"]
    ):
        """Search knowledge base for answers."""
        q = query.lower()
        logger.info(f"Searching for: {q}")
        results = []
        
        # Pricing Keywords
        if any(k in q for k in ["price", "cost", "fee", "charge", "rate", "commission"]):
            results.append(f"Pricing: {json.dumps(self.company_data.get('pricing', 'N/A'))}")
            
        # Products
        for prod in self.company_data.get('products', []):
            if prod['name'].lower() in q or q in prod['name'].lower():
                results.append(f"Product {prod['name']}: {prod['details']}")
                
        # FAQs
        for item in self.company_data.get('faq', []):
            if q in item['question'].lower() or item['question'].lower() in q:
                results.append(f"Q: {item['question']} A: {item['answer']}")
        
        if not results:
            return f"No exact match for '{q}'. General Info: {self.company_data.get('description')}"
            
        return "\n".join(results)

    @function_tool
    async def update_lead(
        self, ctx: RunContext,
        name: Optional[str] = None, company: Optional[str] = None,
        role: Optional[str] = None, use_case: Optional[str] = None,
        team_size: Optional[str] = None, timeline: Optional[str] = None,
        email: Optional[str] = None
    ):
        """Save lead details."""
        updates = []
        for field, val in locals().items():
            if field in ["self", "ctx", "updates"] or val is None: continue
            if self.lead_form.update(field, val):
                updates.append(field)
        
        return f"Updated: {', '.join(updates)}"

    @function_tool
    async def finalize_call(self, ctx: RunContext):
        """Save data and end call."""
        fname = self.lead_form.save_to_file()
        return f"Lead saved to {fname}. Say goodbye."

# --- 4. Entrypoint ---
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()

    # Load data safely inside entrypoint
    data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
    else:
        logger.error("DATA FILE MISSING")

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-matthew", style="Promo", text_pacing=True),
        vad=ctx.proc.userdata["vad"],
    )

    agent = SDRAgent(company_data=data)
    await session.start(agent=agent, room=ctx.room)
    await agent.say("Hi! I'm Rohan from Razorpay. How can I help you?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
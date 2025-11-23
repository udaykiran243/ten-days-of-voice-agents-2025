# import logging

# from dotenv import load_dotenv
# from livekit.agents import (
#     Agent,
#     AgentSession,
#     JobContext,
#     JobProcess,
#     MetricsCollectedEvent,
#     RoomInputOptions,
#     WorkerOptions,
#     cli,
#     metrics,
#     tokenize,
#     # function_tool,
#     # RunContext
# )
# from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
# from livekit.plugins.turn_detector.multilingual import MultilingualModel

# logger = logging.getLogger("agent")

# load_dotenv(".env.local")


# class Assistant(Agent):
#     def __init__(self) -> None:
#         super().__init__(
#             instructions="""You are a helpful voice AI assistant. The user is interacting with you via voice, even if you perceive the conversation as text.
#             You eagerly assist users with their questions by providing information from your extensive knowledge.
#             Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
#             You are curious, friendly, and have a sense of humor.""",
#         )

#     # To add tools, use the @function_tool decorator.
#     # Here's an example that adds a simple weather tool.
#     # You also have to add `from livekit.agents import function_tool, RunContext` to the top of this file
#     # @function_tool
#     # async def lookup_weather(self, context: RunContext, location: str):
#     #     """Use this tool to look up current weather information in the given location.
#     #
#     #     If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.
#     #
#     #     Args:
#     #         location: The location to look up weather information for (e.g. city name)
#     #     """
#     #
#     #     logger.info(f"Looking up weather for {location}")
#     #
#     #     return "sunny with a temperature of 70 degrees."


# def prewarm(proc: JobProcess):
#     proc.userdata["vad"] = silero.VAD.load()


# async def entrypoint(ctx: JobContext):
#     # Logging setup
#     # Add any other context you want in all log entries here
#     ctx.log_context_fields = {
#         "room": ctx.room.name,
#     }

#     # Set up a voice AI pipeline using OpenAI, Cartesia, AssemblyAI, and the LiveKit turn detector
#     session = AgentSession(
#         # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
#         # See all available models at https://docs.livekit.io/agents/models/stt/
#         stt=deepgram.STT(model="nova-3"),
#         # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
#         # See all available models at https://docs.livekit.io/agents/models/llm/
#         llm=google.LLM(
#                 model="gemini-2.5-flash",
#             ),
#         # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
#         # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
#         tts=murf.TTS(
#                 voice="en-US-matthew", 
#                 style="Conversation",
#                 tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
#                 text_pacing=True
#             ),
#         # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
#         # See more at https://docs.livekit.io/agents/build/turns
#         turn_detection=MultilingualModel(),
#         vad=ctx.proc.userdata["vad"],
#         # allow the LLM to generate a response while waiting for the end of turn
#         # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
#         preemptive_generation=True,
#     )

#     # To use a realtime model instead of a voice pipeline, use the following session setup instead.
#     # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
#     # 1. Install livekit-agents[openai]
#     # 2. Set OPENAI_API_KEY in .env.local
#     # 3. Add `from livekit.plugins import openai` to the top of this file
#     # 4. Use the following session setup instead of the version above
#     # session = AgentSession(
#     #     llm=openai.realtime.RealtimeModel(voice="marin")
#     # )

#     # Metrics collection, to measure pipeline performance
#     # For more information, see https://docs.livekit.io/agents/build/metrics/
#     usage_collector = metrics.UsageCollector()

#     @session.on("metrics_collected")
#     def _on_metrics_collected(ev: MetricsCollectedEvent):
#         metrics.log_metrics(ev.metrics)
#         usage_collector.collect(ev.metrics)

#     async def log_usage():
#         summary = usage_collector.get_summary()
#         logger.info(f"Usage: {summary}")

#     ctx.add_shutdown_callback(log_usage)

#     # # Add a virtual avatar to the session, if desired
#     # # For other providers, see https://docs.livekit.io/agents/models/avatar/
#     # avatar = hedra.AvatarSession(
#     #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
#     # )
#     # # Start the avatar and wait for it to join
#     # await avatar.start(session, room=ctx.room)

#     # Start the session, which initializes the voice pipeline and warms up the models
#     await session.start(
#         agent=Assistant(),
#         room=ctx.room,
#         room_input_options=RoomInputOptions(
#             # For telephony applications, use `BVCTelephony` for best results
#             noise_cancellation=noise_cancellation.BVC(),
#         ),
#     )

#     # Join the room and connect to the user
#     await ctx.connect()


# if __name__ == "__main__":
#     cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))


import logging
import json
from typing import Annotated, Optional, List
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
    function_tool,  # Required for tools
    RunContext      # Required for tool context
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# --- 1. Define Order State Logic ---
class OrderState:
    def __init__(self):
        self.data = {
            "drinkType": None,
            "size": None,
            "milk": None,
            "extras": [],
            "name": None
        }

    def update(self, drink_type=None, size=None, milk=None, extras=None, name=None):
        if drink_type: self.data["drinkType"] = drink_type
        if size: self.data["size"] = size
        if milk: self.data["milk"] = milk
        if extras is not None: self.data["extras"] = extras
        if name: self.data["name"] = name
        return self.data

    def is_complete(self):
        # Require Drink, Size, Milk, and Name to be considered complete
        required = ["drinkType", "size", "milk", "name"]
        return all(self.data.get(k) for k in required)

    def save_to_file(self):
        # Create 'orders' folder if it doesn't exist
        os.makedirs("orders", exist_ok=True)

        # Save inside that folder
        filename = f"orders/order_{self.data.get('name', 'customer')}.json"

        with open(filename, "w") as f:
            json.dump(self.data, f, indent=2)
        return filename
        return filename


# --- 2. Update Assistant with Tools and Persona ---
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a friendly and energetic barista at 'Java Gen'. 
            Your goal is to take a complete coffee order from the user. 
            
            You MUST collect the following information: 
            1. Drink Type 
            2. Size 
            3. Milk Preference 
            4. Name 
            (Extras are optional).

            Conversation Rules:
            - Ask one clarifying question at a time to fill the missing fields.
            - Be conversational.
            - IMMEDIATELY call the `update_order` tool when the user provides new details.
            - Once you have Drink, Size, Milk, and Name, read the order back to confirm.
            - If confirmed, call `finalize_order` to save the order.
            """,
        )
        # Initialize state for this agent instance
        self.order_state = OrderState()

    @function_tool
    async def update_order(
        self, 
        ctx: RunContext, 
        drink_type: Annotated[Optional[str], "The type of coffee/drink (e.g. Latte, Cappuccino)"] = None,
        size: Annotated[Optional[str], "Size of the drink (Small, Medium, Large)"] = None,
        milk: Annotated[Optional[str], "Milk preference (Whole, Oat, Almond, None)"] = None,
        extras: Annotated[Optional[List[str]], "List of extra additions (e.g. Sugar, Syrup)"] = None,
        name: Annotated[Optional[str], "The customer's name"] = None,
    ):
        """
        Update the customer's order details. Call this tool whenever the user provides new information regarding their order.
        """
        current_data = self.order_state.update(drink_type, size, milk, extras, name)
        logger.info(f"Order Updated: {current_data}")
        return f"Order updated. Current state: {current_data}"

    @function_tool
    async def finalize_order(self, ctx: RunContext):
        """
        Finalize the order. Call this ONLY when you have confirmed the Drink, Size, Milk, and Name with the customer.
        """
        if not self.order_state.is_complete():
            return "Order is missing details. You cannot finalize yet. Ask for the missing fields."
        
        filename = self.order_state.save_to_file()
        return f"Order saved to {filename}. You can now thank the customer and close."


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(
                model="gemini-2.5-flash",
            ),
        tts=murf.TTS(
                voice="en-US-matthew", 
                style="Conversation",
                tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
                text_pacing=True
            ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
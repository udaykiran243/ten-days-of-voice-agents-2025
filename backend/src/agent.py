import logging
import json
import os
import asyncio
from datetime import datetime
from typing import Annotated, List

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
logger = logging.getLogger("grocery-agent")

# --- 1. CONFIG & DATA ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(SCRIPT_DIR, "grocery_catalog.json")
ORDERS_FILE = os.path.join(SCRIPT_DIR, "orders.json")

# Simple Recipe Map
RECIPES = {
    "sandwich": ["bread", "pb", "jam"],
    "pasta": ["pasta", "sauce", "cheese"],
    "breakfast": ["eggs", "bread", "milk", "banana"],
    "fruit salad": ["apple", "banana"]
}

# --- 2. Logic Class ---
class StoreManager:
    def __init__(self):
        self.catalog = []
        self._load_catalog()
        self._ensure_orders_file()

    def _load_catalog(self):
        if os.path.exists(CATALOG_FILE):
            with open(CATALOG_FILE, "r") as f:
                self.catalog = json.load(f)

    def _ensure_orders_file(self):
        if not os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, "w") as f:
                json.dump([], f)

    def get_item_by_name(self, name_query: str):
        name_query = name_query.lower()
        for item in self.catalog:
            if item["id"] == name_query: return item
        for item in self.catalog:
            if name_query in item["name"].lower(): return item
        return None

    def save_order(self, cart_items: dict, total: float):
        order_id = f"ORD-{int(datetime.now().timestamp())}"
        order = {
            "id": order_id,
            "timestamp": datetime.now().isoformat(),
            "items": cart_items,
            "total": total,
            "status": "received"
        }
        
        try:
            with open(ORDERS_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = []
            
        data.append(order)
        
        with open(ORDERS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        
        return order_id

    def update_mock_statuses(self):
        try:
            with open(ORDERS_FILE, "r") as f:
                orders = json.load(f)
            
            now = datetime.now()
            updated = False
            
            for order in orders:
                order_time = datetime.fromisoformat(order["timestamp"])
                elapsed = (now - order_time).total_seconds()
                
                new_status = order["status"]
                if elapsed > 90: new_status = "delivered"
                elif elapsed > 60: new_status = "out_for_delivery"
                elif elapsed > 30: new_status = "being_prepared"
                
                if new_status != order["status"]:
                    order["status"] = new_status
                    updated = True
            
            if updated:
                with open(ORDERS_FILE, "w") as f:
                    json.dump(orders, f, indent=2)
            
            return orders
        except Exception as e:
            logger.error(f"Error updating statuses: {e}")
            return []

# --- 3. The Agent ---
class GroceryAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="""
            You are 'FreshBot', a friendly grocery ordering assistant.
            
            STARTUP INSTRUCTION:
            - When the conversation begins, immediately GREET the user and ask "What groceries do you need today?"
            
            CAPABILITIES:
            1. **Take Orders:** Add items to the user's cart using `add_to_cart`. 
               - If they ask for "ingredients for pasta/sandwich", use `add_recipe_ingredients`.
            2. **Manage Cart:** Remove items using `remove_from_cart` or show the cart total using `view_cart`.
            3. **Place Order:** When the user is done, summarize the total and call `place_order`.
            4. **Tracking:** If the user asks "Where is my order?", use `track_orders`.
            
            BEHAVIOR:
            - If an item isn't found, suggest something similar.
            - Always confirm price when adding items.
            """
        )
        self.store = StoreManager()
        self.cart = {}

    @function_tool
    async def get_catalog_items(self, ctx: RunContext):
        """List available items in the store."""
        return json.dumps(self.store.catalog)

    @function_tool
    async def add_to_cart(
        self, 
        ctx: RunContext, 
        item_name: Annotated[str, "Name of the item"], 
        quantity: Annotated[int, "Quantity"] = 1
    ):
        """Add a specific item to the cart."""
        item = self.store.get_item_by_name(item_name)
        if not item:
            return f"Sorry, we don't have '{item_name}'."
        
        current_qty = self.cart.get(item["id"], 0)
        self.cart[item["id"]] = current_qty + quantity
        return f"Added {quantity}x {item['name']} to cart."

    @function_tool
    async def remove_from_cart(
        self, 
        ctx: RunContext, 
        item_name: Annotated[str, "Name of the item to remove"], 
        quantity: Annotated[int, "Quantity to remove (0 to remove all)"] = 0
    ):
        """Remove a specific item from the cart."""
        item = self.store.get_item_by_name(item_name)
        if not item:
            return f"Could not find '{item_name}' in catalog."
        
        if item["id"] not in self.cart:
            return f"'{item['name']}' is not in your cart."
            
        current_qty = self.cart[item["id"]]
        
        if quantity <= 0 or quantity >= current_qty:
            # Remove the item entirely
            del self.cart[item["id"]]
            return f"Removed all {item['name']} from your cart."
        else:
            # Decrease quantity
            self.cart[item["id"]] = current_qty - quantity
            return f"Removed {quantity}x {item['name']}. You have {self.cart[item['id']]} left."

    @function_tool
    async def add_recipe_ingredients(
        self,
        ctx: RunContext,
        recipe_name: Annotated[str, "Name of the dish (sandwich, pasta, breakfast)"]
    ):
        """Intelligently adds all ingredients for a specific recipe/dish."""
        recipe_key = next((k for k in RECIPES if k in recipe_name.lower()), None)
        if not recipe_key:
            return f"I don't have a pre-set bundle for '{recipe_name}'."
        
        added_items = []
        for item_id in RECIPES[recipe_key]:
            self.cart[item_id] = self.cart.get(item_id, 0) + 1
            item_details = next((i for i in self.store.catalog if i["id"] == item_id), None)
            if item_details: added_items.append(item_details["name"])
            
        return f"Added ingredients for {recipe_name} ({', '.join(added_items)})."

    @function_tool
    async def view_cart(self, ctx: RunContext):
        """Check what is currently in the cart and the total price."""
        if not self.cart:
            return "Cart is empty."
        
        summary = []
        total = 0.0
        for item_id, qty in self.cart.items():
            item = next((i for i in self.store.catalog if i["id"] == item_id), None)
            if item:
                cost = item["price"] * qty
                total += cost
                summary.append(f"{qty}x {item['name']} (${cost:.2f})")
        
        return f"Cart: {', '.join(summary)}. Total: ${total:.2f}"

    @function_tool
    async def place_order(self, ctx: RunContext):
        """Finalize the order and save it."""
        if not self.cart:
            return "Cart is empty. Cannot place order."
        
        total = 0.0
        for item_id, qty in self.cart.items():
            item = next((i for i in self.store.catalog if i["id"] == item_id), None)
            if item: total += item["price"] * qty
            
        order_id = self.store.save_order(self.cart, total)
        self.cart = {}
        return f"Order placed! ID: {order_id}. Total: ${total:.2f}. Status: Received."

    @function_tool
    async def track_orders(self, ctx: RunContext):
        """Check status of recent orders."""
        orders = self.store.update_mock_statuses()
        if not orders: return "No order history found."
        
        recent = orders[-3:]
        details = []
        for o in recent:
            details.append(f"Order {o['id']}: {o['status']} (Total ${o['total']})")
        return "\n".join(details)

# --- 4. Entrypoint ---

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    try:
        ctx.log_context_fields = {"room": ctx.room.name}
        await ctx.connect()

        session = AgentSession(
            stt=deepgram.STT(model="nova-3"),
            llm=google.LLM(model="gemini-2.5-flash"),
            tts=murf.TTS(
                voice="en-US-matthew", 
                style="Conversation",
                text_pacing=True
            ),
            vad=ctx.proc.userdata["vad"],
        )

        agent = GroceryAgent()
        await session.start(agent=agent, room=ctx.room)
        
        # Greet the user automatically
        await session.say("Hi! Welcome to FreshBot. I can help you order groceries. What do you need today?", allow_interruptions=True)

    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
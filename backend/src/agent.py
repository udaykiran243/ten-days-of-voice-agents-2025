import logging
import json
import os
import asyncio
from datetime import datetime
from typing import Annotated, List, Dict, Optional

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
logger = logging.getLogger("commerce-agent")

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(SCRIPT_DIR, "products.json")
ORDERS_FILE = os.path.join(SCRIPT_DIR, "orders.json")

# --- 1. MERCHANT LAYER (The Logic) ---
class MerchantAPI:
    def __init__(self):
        self.catalog = self._load_catalog()
        self._ensure_orders_file()
        # In-memory cart for the session: {product_id: quantity}
        self.cart: Dict[str, int] = {}

    def _load_catalog(self):
        if os.path.exists(CATALOG_FILE):
            # FIX: Added encoding="utf-8" for Windows compatibility with emojis
            with open(CATALOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _ensure_orders_file(self):
        if not os.path.exists(ORDERS_FILE):
            # FIX: Added encoding="utf-8"
            with open(ORDERS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)

    def search_products(self, query: str):
        """Filter catalog based on keyword."""
        query = query.lower()
        results = []
        for item in self.catalog:
            if (query in item["name"].lower() or 
                query in item["category"].lower() or 
                query in item["description"].lower()):
                results.append(item)
        return results

    def get_product_by_name(self, name: str):
        """Fuzzy match product name to ID."""
        for item in self.catalog:
            if name.lower() in item["name"].lower():
                return item
        return None

    def add_to_cart(self, product_id: str, qty: int):
        if product_id in self.cart:
            self.cart[product_id] += qty
        else:
            self.cart[product_id] = qty
        return self.get_cart_summary()
        
    def remove_from_cart(self, product_id: str):
        if product_id in self.cart:
            del self.cart[product_id]
        return self.get_cart_summary()

    def get_cart_summary(self):
        items = []
        total = 0
        for pid, qty in self.cart.items():
            prod = next((p for p in self.catalog if p["id"] == pid), None)
            if prod:
                line_total = prod["price"] * qty
                total += line_total
                items.append({
                    "id": prod["id"],
                    "name": prod["name"],
                    "qty": qty,
                    "price": prod["price"],
                    "total": line_total,
                    "currency": prod["currency"]
                })
        return {"items": items, "grand_total": total}

    def create_order(self):
        if not self.cart:
            return None
            
        summary = self.get_cart_summary()
        
        order = {
            "id": f"ORD-{int(datetime.now().timestamp())}",
            "created_at": datetime.now().isoformat(),
            "status": "CONFIRMED",
            "items": summary["items"],
            "total_amount": summary["grand_total"],
            "currency": "INR"
        }
        
        # Persist
        try:
            # FIX: Added encoding="utf-8"
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
            
        history.append(order)
        
        # FIX: Added encoding="utf-8"
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
            
        # Clear cart
        self.cart = {}
        return order

    def get_last_order(self):
        try:
            # FIX: Added encoding="utf-8"
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            if history: return history[-1]
        except:
            pass
        return None

# --- 2. THE AGENT ---
class ShoppingAgent(Agent):
    def __init__(self, room):
        super().__init__(
            instructions="""
            You are 'ShopBot', an intelligent shopping assistant for a lifestyle brand.
            
            PROTOCOL:
            1. **Explore:** When user asks about products, use `search_catalog`. Describe them briefly (Name + Price).
            2. **Select:** If user wants to buy, use `add_to_cart`. Confirm the addition.
            3. **Manage:** If user wants to remove items, use `remove_from_cart`.
            4. **Checkout:** When user says "buy", "checkout", or "place order", use `checkout`.
            5. **History:** If user asks "what did I buy?", use `get_last_order_summary`.
            
            TONE: Helpful, Efficient, Modern.
            """
        )
        self.merchant = MerchantAPI()
        self.room = room

    async def sync_ui(self, event_type="CATALOG", data=None):
        """Sends data to Frontend for visual updates."""
        payload = {
            "type": event_type,
            "data": data
        }
        try:
            # Serialize payload to JSON string, then encode to bytes
            json_str = json.dumps(payload)
            await self.room.local_participant.publish_data(json_str, topic="shop_update")
        except Exception as e:
            logger.error(f"UI Sync Error: {e}")

    @function_tool
    async def search_catalog(self, ctx: RunContext, query: Annotated[str, "Search term (e.g. 'hoodie', 'mug')"]):
        """Finds products in the catalog."""
        items = self.merchant.search_products(query)
        if not items:
            return "No products found matching that description."
        return f"Found {len(items)} items: {json.dumps(items)}"

    @function_tool
    async def add_to_cart(self, ctx: RunContext, product_name: str, quantity: int = 1):
        """Adds item to cart by name."""
        item = self.merchant.get_product_by_name(product_name)
        if not item:
            return f"Product '{product_name}' not found."
        
        summary = self.merchant.add_to_cart(item["id"], quantity)
        
        # Update UI Cart
        await self.sync_ui("CART_UPDATE", summary)
        
        return f"Added {quantity}x {item['name']}. Cart Total: {summary['grand_total']} INR."

    @function_tool
    async def remove_from_cart(self, ctx: RunContext, product_name: str):
        """Removes an item from the cart."""
        item = self.merchant.get_product_by_name(product_name)
        if not item: return "Item not found."
        
        summary = self.merchant.remove_from_cart(item["id"])
        await self.sync_ui("CART_UPDATE", summary)
        return f"Removed {item['name']}. New Total: {summary['grand_total']} INR."

    @function_tool
    async def checkout(self, ctx: RunContext):
        """Finalizes the purchase."""
        order = self.merchant.create_order()
        if not order:
            return "Cart is empty."
        
        # Update UI Order Success
        await self.sync_ui("ORDER_PLACED", order)
        
        return f"Order placed! ID: {order['id']}. Total: {order['total_amount']} INR."

    @function_tool
    async def get_last_order_summary(self, ctx: RunContext):
        """Retrieves details of the most recent order."""
        order = self.merchant.get_last_order()
        if not order: return "No previous orders found."
        return json.dumps(order)

# --- 3. ENTRYPOINT ---

# Define globally for Windows multiprocessing safety
def prewarm(proc: JobProcess):
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except:
        proc.userdata["vad"] = silero.VAD.load(use_onnx=False)

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()

    # Load VAD
    if "vad" in ctx.proc.userdata:
        vad = ctx.proc.userdata["vad"]
    else:
        try:
            vad = silero.VAD.load()
        except:
            vad = silero.VAD.load(use_onnx=False)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-alicia", style="Promo", text_pacing=True),
        vad=vad,
    )

    agent = ShoppingAgent(room=ctx.room)
    await session.start(agent=agent, room=ctx.room)
    
    # Initial Sync: Send Catalog to UI immediately
    await agent.sync_ui("CATALOG_INIT", agent.merchant.catalog)
    
    await session.say("Welcome to the Store! I can help you find clothes, mugs, or stickers. What are you looking for?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
'use client';

import { 
  RoomAudioRenderer, 
  StartAudio, 
  useDataChannel,
  useRoomContext,
  useConnectionState,
  Chat
} from '@livekit/components-react';
import { ConnectionState } from 'livekit-client';
import type { AppConfig } from '@/app-config';
import { SessionProvider } from '@/components/app/session-provider';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/livekit/toaster';
import { useState } from 'react';

interface AppProps {
  appConfig: AppConfig;
}

// --- 1. Store State Hook ---
const useStoreState = () => {
  const [catalog, setCatalog] = useState<any[]>([]);
  const [cart, setCart] = useState<any>({ items: [], grand_total: 0 });
  const [lastOrder, setLastOrder] = useState<any>(null);

  useDataChannel((...args: any[]) => {
    let payload: Uint8Array | undefined;
    
    // Handle new/old SDK signatures
    if (args.length === 1 && args[0] && typeof args[0] === 'object' && 'payload' in args[0]) {
        payload = args[0].payload;
    } else {
        payload = args[0];
    }
    
    if (!payload) return;

    try {
      const text = new TextDecoder().decode(payload);
      const msg = JSON.parse(text);
      
      if (msg.type === "CATALOG_INIT") setCatalog(msg.data);
      if (msg.type === "CART_UPDATE") setCart(msg.data);
      if (msg.type === "ORDER_PLACED") {
          setLastOrder(msg.data);
          setCart({ items: [], grand_total: 0 }); // Clear UI cart
      }
    } catch (e) { console.error("Parse Error", e); }
  });

  return { catalog, cart, lastOrder };
};

// --- 2. Components ---

const ProductCard = ({ item }: { item: any }) => (
  <div className="bg-white p-4 rounded-lg shadow-md border border-gray-100 hover:shadow-lg transition-shadow flex flex-col">
    <div className="h-24 bg-gray-50 rounded mb-3 flex items-center justify-center text-4xl">{item.image}</div>
    <h3 className="font-bold text-gray-800 text-sm mb-1">{item.name}</h3>
    <p className="text-xs text-gray-500 mb-3 flex-1">{item.description}</p>
    <div className="flex justify-between items-center mt-auto">
      <span className="font-bold text-indigo-600">₹{item.price}</span>
      <span className="text-[10px] bg-gray-100 px-2 py-1 rounded text-gray-600 border border-gray-200">In Stock</span>
    </div>
  </div>
);

const CartPanel = ({ cart }: { cart: any }) => (
  <div className="bg-white p-4 rounded-lg border border-gray-200 h-full flex flex-col shadow-sm">
    <h3 className="font-bold text-gray-700 border-b pb-3 mb-3 flex items-center gap-2">
        🛒 Your Cart <span className="text-xs font-normal text-gray-400">({cart.items.length} items)</span>
    </h3>
    <div className="flex-1 overflow-y-auto space-y-3 pr-2">
        {cart.items.length === 0 && (
            <div className="text-center py-10 text-gray-400 text-sm">
                Your cart is empty.
                <br/>Ask the agent to add items!
            </div>
        )}
        {cart.items.map((item: any, i: number) => (
            <div key={i} className="flex justify-between text-sm text-gray-700 bg-gray-50 p-2 rounded border border-gray-100">
                <div>
                    <div className="font-medium">{item.name}</div>
                    <div className="text-xs text-gray-500">Qty: {item.qty} x ₹{item.price}</div>
                </div>
                <div className="font-bold">₹{item.total}</div>
            </div>
        ))}
    </div>
    <div className="mt-auto pt-4 border-t border-gray-200">
        <div className="flex justify-between font-bold text-gray-800 text-lg mb-2">
            <span>Total</span>
            <span>₹{cart.grand_total}</span>
        </div>
        <div className="text-xs text-center text-gray-400">Say "Checkout" to place order</div>
    </div>
  </div>
);

const OrderReceipt = ({ order }: { order: any }) => {
    if (!order) return null;
    return (
        <div className="absolute inset-0 bg-black/60 flex items-center justify-center z-[100] backdrop-blur-sm animate-in fade-in">
            <div className="bg-white p-6 rounded-xl shadow-2xl max-w-sm w-full transform scale-100 animate-in zoom-in duration-200 border border-gray-200">
                <div className="text-center mb-6">
                    <div className="w-14 h-14 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto text-3xl mb-3">✓</div>
                    <h2 className="text-2xl font-bold text-gray-900">Order Placed!</h2>
                    <p className="text-xs text-gray-500 mt-1 font-mono">ID: {order.id}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3 border border-gray-100 mb-4">
                    <div className="space-y-2">
                        {order.items.map((item: any, i: number) => (
                            <div key={i} className="flex justify-between text-sm text-gray-700">
                                <span>{item.qty}x {item.name}</span>
                                <span className="font-medium">₹{item.total}</span>
                            </div>
                        ))}
                    </div>
                    <div className="border-t border-dashed border-gray-300 my-3"></div>
                    <div className="flex justify-between font-bold text-lg text-gray-900">
                        <span>Total Paid</span>
                        <span>₹{order.total_amount}</span>
                    </div>
                </div>
                <button onClick={() => window.location.reload()} className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-bold shadow-md transition-all active:scale-95">
                    Start New Order
                </button>
            </div>
        </div>
    );
}

const Storefront = () => {
  const { catalog, cart, lastOrder } = useStoreState();
  const  state  = useConnectionState();

  return (
    <div className="flex h-full w-full bg-gray-50 text-gray-900 relative overflow-hidden font-sans">
       {/* Order Modal */}
       <OrderReceipt order={lastOrder} />

       {/* Left: Catalog */}
       <div className="flex-1 p-6 md:p-8 overflow-y-auto flex flex-col">
          <header className="mb-8 flex justify-between items-center bg-white p-4 rounded-xl shadow-sm border border-gray-200">
             <div className="flex items-center gap-3">
                <div className="bg-indigo-600 text-white p-2 rounded-lg font-bold text-xl">🛍️</div>
                <div>
                    <h1 className="text-xl font-bold text-gray-900">Agentic Store</h1>
                    <div className="text-xs text-gray-500">Voice-Powered Shopping</div>
                </div>
             </div>
             <div className={`px-4 py-1.5 rounded-full text-xs font-bold tracking-wide border ${state === ConnectionState.Connected ? 'bg-green-50 text-green-700 border-green-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                {state === ConnectionState.Connected ? '● AGENT ONLINE' : '○ CONNECTING...'}
             </div>
          </header>
          
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
             {catalog.length === 0 && state === ConnectionState.Connected && (
                 <div className="col-span-full flex flex-col items-center justify-center py-20 text-gray-400">
                    <div className="animate-spin text-3xl mb-4">⏳</div>
                    <p>Loading catalog from Agent...</p>
                 </div>
             )}
             {catalog.map((item) => (
                 <ProductCard key={item.id} item={item} />
             ))}
          </div>
       </div>

       {/* Right: Sidebar */}
       <div className="w-96 bg-white border-l border-gray-200 flex flex-col shadow-xl z-10">
          {/* Top: Visualizer */}
          <div className="h-56 bg-slate-900 relative overflow-hidden flex items-center justify-center border-b border-gray-800">
              <div className="absolute inset-0 opacity-20 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-indigo-500 via-slate-900 to-black"></div>
              <div className="z-10 w-full h-full opacity-80"><ViewController /></div>
              <div className="absolute bottom-3 left-4 text-xs text-indigo-300 font-mono tracking-widest">VOICE_INTERFACE_ACTIVE</div>
          </div>

          {/* Bottom: Cart */}
          <div className="flex-1 p-6 overflow-hidden bg-gray-50">
              <CartPanel cart={cart} />
          </div>
       </div>
    </div>
  );
};

export function App({ appConfig }: AppProps) {
  return (
    <SessionProvider appConfig={appConfig}>
      <div className="h-svh w-full bg-gray-50">
        <Storefront />
      </div>
      <StartAudio label="START SHOPPING" />
      <RoomAudioRenderer />
      <Toaster />
    </SessionProvider>
  );
}
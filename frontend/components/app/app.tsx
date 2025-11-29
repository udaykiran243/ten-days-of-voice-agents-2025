'use client';

import { 
  RoomAudioRenderer, 
  StartAudio, 
  Chat,
  useConnectionState,
  useDataChannel,
  useRoomContext
} from '@livekit/components-react';
import { ConnectionState } from 'livekit-client';
import type { AppConfig } from '@/app-config';
import { SessionProvider } from '@/components/app/session-provider';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/livekit/toaster';
import { useState, useRef } from 'react';

interface AppProps {
  appConfig: AppConfig;
}

// --- 1. Game State Hook ---
const useGameState = () => {
  const [state, setState] = useState({
    player: {
      hp: 100,
      max_hp: 100,
      ram: 80,
      max_ram: 100,
      status: "Healthy",
      inventory: ["Cyberdeck", "Pistol"]
    },
    world: {
      location: "Unknown",
      danger_level: "Low"
    },
    log: [] as string[]
  });

  const room = useRoomContext();

  useDataChannel((payload, participant, topic) => {
    // Handle older SDK version if payload is wrapped in an object
    // @ts-ignore
    const rawPayload = payload?.payload ?? payload; 

    if (!rawPayload) return;

    const text = new TextDecoder().decode(rawPayload);
    try {
      const data = JSON.parse(text);
      
      if (topic === "game_state_update") {
        setState(data);
      } 
      else if (topic === "system" && data.type === "SAVE_ACK") {
        console.log("Received save data, downloading...");
        const blob = new Blob([JSON.stringify(data.state, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cyberpunk_save_${new Date().getTime()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
    } catch (e) { console.error("Data Packet Error:", e); }
  });

  return { state, room };
};

// --- 2. Visual Components ---

const CRTOverlay = () => (
  <div className="pointer-events-none absolute inset-0 z-40 overflow-hidden h-full w-full">
    <div className="absolute inset-0 bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(255,0,0,0.06),rgba(0,255,0,0.02),rgba(0,0,255,0.06))] z-50 bg-[length:100%_2px,3px_100%] pointer-events-none opacity-20" />
    <div className="absolute inset-0 bg-black opacity-5 animate-pulse pointer-events-none" />
  </div>
);

const StatusPanel = ({ game }: any) => {
  const hpPercent = (game.player.hp / game.player.max_hp) * 100;
  const ramPct = (game.player.ram / game.player.max_ram) * 100;

  return (
    <div className="border-r border-cyan-900/50 bg-black/80 p-6 text-cyan-500 font-mono text-xs w-72 flex flex-col gap-8 hidden md:flex shadow-[0_0_15px_rgba(0,255,255,0.1)] relative z-10">
      <div>
        <h3 className="text-cyan-300 border-b border-cyan-700 mb-3 pb-1 tracking-[0.2em] font-bold">OPERATIVE STATUS</h3>
        <div className="space-y-3">
          <div className="flex justify-between">
            <span>HP [{game.player.status.toUpperCase()}]</span> 
            <span className={`${hpPercent < 40 ? 'text-red-500 animate-pulse' : 'text-green-400'} font-bold`}>{game.player.hp}%</span>
          </div>
          <div className="w-full bg-gray-900 h-1">
            <div className={`h-1 transition-all duration-500 ${hpPercent < 40 ? 'bg-red-500 shadow-[0_0_10px_red]' : 'bg-green-500 shadow-[0_0_10px_lime]'}`} style={{ width: `${hpPercent}%` }} />
          </div>
          
          <div className="flex justify-between"><span>RAM [CYBER]</span> <span className="text-yellow-400 font-bold">{game.player.ram}%</span></div>
          <div className="w-full bg-gray-900 h-1">
            <div className="bg-yellow-500 h-1 transition-all duration-500 shadow-[0_0_10px_yellow]" style={{ width: `${ramPct}%` }} />
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-cyan-300 border-b border-cyan-700 mb-3 pb-1 tracking-[0.2em] font-bold">INVENTORY</h3>
        <ul className="space-y-2 opacity-80 font-mono">
          {game.player.inventory.map((item: string, i: number) => (
             <li key={i} className="flex items-center gap-2"><span className="text-cyan-700">{'>'}</span> {item}</li>
          ))}
        </ul>
      </div>
      
      <div className="mt-auto">
        <h3 className="text-red-400 border-b border-red-900 mb-3 pb-1 tracking-[0.2em] font-bold">CURRENT LOCATION</h3>
        <div className="border border-red-900/50 bg-red-950/10 p-3 rounded text-center">
             <p className="text-red-500 animate-pulse font-bold text-sm">{game.world.location.toUpperCase()}</p>
             <p className="text-red-800/60 text-[10px] mt-1">ALERT LEVEL: {game.world.danger_level.toUpperCase()}</p>
        </div>
      </div>
    </div>
  );
};

const ActionLog = ({ game }: any) => {
    const recentLogs = game.log.slice(-3);
    return (
        <div className="border border-cyan-800/50 p-4 rounded bg-cyan-950/10 flex-1 overflow-hidden flex flex-col">
            <h4 className="text-xs mb-3 border-b border-cyan-800 pb-2 tracking-widest text-cyan-400">ACTION LOG</h4>
            <div className="text-[10px] text-cyan-700/80 space-y-2 font-mono flex-1">
                {recentLogs.map((log: string, i: number) => (
                    <p key={i} className="animate-in fade-in slide-in-from-bottom-2 duration-500">{'>'} {log}</p>
                ))}
                <p className="mt-4 text-cyan-500 animate-pulse">{'>'} Awaiting input...</p>
            </div>
        </div>
    );
}

// --- 3. Bottom Control Panel (New Component) ---
const ControlPanel = ({ room }: any) => {
  const state = useConnectionState();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSave = async () => {
    if (!room) return;
    const payload = new TextEncoder().encode(JSON.stringify({ type: "SAVE_REQ" }));
    await room.localParticipant.publishData(payload, { reliable: true });
  };

  const handleLoad = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !room) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const content = JSON.parse(e.target?.result as string);
        const payload = new TextEncoder().encode(JSON.stringify({ type: "LOAD_REQ", state: content }));
        await room.localParticipant.publishData(payload, { reliable: true });
      } catch (err) {
        console.error("Invalid save file", err);
      }
    };
    reader.readAsText(file);
  };

  if (state !== ConnectionState.Connected) return null;

  return (
    <div className="absolute bottom-8 left-1/2 transform -translate-x-1/2 flex gap-4 z-[100] pointer-events-auto">
        <button 
          onClick={handleSave} 
          className="px-4 py-2 text-xs font-bold bg-cyan-900/90 hover:bg-cyan-700 border border-cyan-500 shadow-[0_0_15px_rgba(0,255,255,0.3)] rounded text-cyan-300 transition-all active:scale-95 tracking-wider"
        >
          SAVE_STATE
        </button>
        <button 
          onClick={() => fileInputRef.current?.click()} 
          className="px-4 py-2 text-xs font-bold bg-yellow-900/90 hover:bg-yellow-700 border border-yellow-500 shadow-[0_0_15px_rgba(255,255,0,0.3)] rounded text-yellow-300 transition-all active:scale-95 tracking-wider"
        >
          LOAD_STATE
        </button>
        <input 
          type="file" 
          ref={fileInputRef} 
          className="hidden" 
          accept=".json" 
          onChange={handleLoad} 
        />
    </div>
  );
};

// --- 4. Header ---
const CyberHeader = () => {
  const state = useConnectionState();
  return (
    <header className="border-b border-cyan-900/50 bg-black/90 p-4 px-6 flex justify-between items-center text-cyan-500 font-mono shadow-lg relative z-[100]">
      <div className="flex items-center gap-3">
          <div className="w-3 h-3 bg-cyan-500 rounded-full animate-ping"></div>
          <div className="text-xl font-bold tracking-[0.15em] text-cyan-100 drop-shadow-[0_0_10px_rgba(0,255,255,0.8)]">
            NEO-VERIDIA <span className="text-cyan-700">//</span> NET.LINK
          </div>
      </div>
      <div className="flex items-center gap-4 text-xs border border-cyan-900/50 px-3 py-1 rounded bg-cyan-950/20">
          <span className="opacity-50">LINK STATUS:</span>
          <span className={`${state === ConnectionState.Connected ? 'text-green-400' : 'text-red-500'} font-bold tracking-wider`}>
            {state === ConnectionState.Connected ? 'SECURE' : `${state}`.toUpperCase()}
          </span>
      </div>
    </header>
  );
};

// --- 5. Main Dashboard ---
const GameDashboard = () => {
  const { state, room } = useGameState();

  return (
    <div className="flex flex-col h-full w-full absolute inset-0 z-10 pointer-events-auto">
      <CyberHeader />
      
      <div className="flex flex-1 overflow-hidden relative">
        {/* Left Panel */}
        <StatusPanel game={state} />

        {/* Center Terminal */}
        <div className="flex-1 flex flex-col bg-stone-950 relative p-4 md:p-8">
             <div className="absolute inset-0 bg-[linear-gradient(rgba(0,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(0,255,255,0.03)_1px,transparent_1px)] bg-[size:40px_40px] pointer-events-none" />
             <div className="flex-1 overflow-hidden rounded-lg border border-cyan-800/50 bg-black/80 shadow-[0_0_30px_rgba(0,0,0,0.8)] relative">
                <div className="absolute top-0 left-0 right-0 bg-cyan-950/30 border-b border-cyan-900/50 p-1 px-2 text-[10px] text-cyan-600 tracking-widest">
                    TERMINAL_OUTPUT_LOG_V.0.9.2
                </div>
                <div className="h-full pt-6">
                    <Chat style={{ height: '100%', background: 'transparent', fontFamily: 'monospace' }} />
                </div>
             </div>
        </div>

        {/* Right Panel */}
        <div className="w-80 border-l border-cyan-900/50 bg-black/80 p-4 flex flex-col gap-4 hidden lg:flex shadow-[-10px_0_20px_rgba(0,0,0,0.5)]">
             <div className="h-64 border border-cyan-700/50 bg-black rounded-lg relative overflow-hidden shadow-[0_0_15px_rgba(0,255,255,0.1)]">
                <div className="absolute top-2 left-2 text-[10px] text-cyan-600 tracking-widest z-10">GM_AUDIO_STREAM</div>
                <div className="absolute bottom-2 right-2 text-[10px] text-red-500 animate-pulse z-10">● LIVE</div>
                <ViewController />
             </div>
             <ActionLog game={state} />
        </div>
      </div>
      
      {/* Bottom Controls */}
      <ControlPanel room={room} />

      {/* Mobile Fab */}
      <div className="lg:hidden absolute bottom-24 right-4 w-32 h-32 z-50 border border-cyan-500/50 rounded-full overflow-hidden bg-black/90 shadow-[0_0_20px_rgba(0,255,255,0.3)]">
        <ViewController />
      </div>
    </div>
  );
};

export function App({ appConfig }: AppProps) {
  return (
    <SessionProvider appConfig={appConfig}>
      <div className="relative h-svh bg-black overflow-hidden">
        <div className="absolute inset-0 bg-[linear-gradient(rgba(0,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(0,255,255,0.03)_1px,transparent_1px)] bg-[size:40px_40px]"></div>
        <CRTOverlay />
        <GameDashboard />
      </div>

      <StartAudio label="JACK IN" />
      <RoomAudioRenderer />
      <Toaster />
    </SessionProvider>
  );
}
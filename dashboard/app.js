const API_URL = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/ws/logs";

const elements = {
  dailyPnl: document.getElementById("dailyPnl"),
  killSwitches: document.getElementById("killSwitches"),
  completedWindows: document.getElementById("completedWindows"),
  botStateLabel: document.getElementById("botStateLabel"),
  terminalOutput: document.getElementById("terminalOutput")
};

// Polling interval for fast API metrics
async function fetchMetrics() {
  try {
    const res = await fetch(`${API_URL}/api/metrics`);
    if (!res.ok) return;
    const data = await res.json();
    
    // Update DOM
    elements.dailyPnl.textContent = `₦${data.daily_pnl_ngn.toLocaleString()}`;
    if (data.daily_pnl_ngn < 0) {
      elements.dailyPnl.style.color = "var(--warning)";
    } else {
      elements.dailyPnl.style.color = "var(--text-bright)";
    }

    elements.killSwitches.textContent = data.kill_switched_windows;
    elements.completedWindows.textContent = data.completed_windows;

    const state = data.bot_status.toUpperCase();
    elements.botStateLabel.textContent = `SYSTEM ${state}`;
    if (state === "PAUSED" || state === "STOP") {
      document.querySelector('.header-status').style.borderColor = "var(--warning)";
      document.querySelector('.header-status').style.color = "var(--warning)";
      document.querySelector('.orb').style.backgroundColor = "var(--warning)";
      document.querySelector('.orb').style.boxShadow = "0 0 15px var(--warning)";
    } else {
      document.querySelector('.header-status').style.borderColor = "var(--accent-glow)";
      document.querySelector('.header-status').style.color = "var(--accent-color)";
      document.querySelector('.orb').style.backgroundColor = "var(--accent-color)";
      document.querySelector('.orb').style.boxShadow = "0 0 15px var(--accent-color)";
    }

  } catch (error) {
    console.warn("Metrics backend not reachable:", error);
    elements.botStateLabel.textContent = "API OFFLINE";
    document.querySelector('.header-status').style.borderColor = "#6c7075";
    document.querySelector('.header-status').style.color = "#6c7075";
    document.querySelector('.orb').style.backgroundColor = "#6c7075";
    document.querySelector('.orb').style.boxShadow = "none";
  }
}

// Command dispatch
async function sendCommand(cmd) {
  try {
    const res = await fetch(`${API_URL}/api/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    console.log("Command executed:", data);
    // Force immediate refresh
    fetchMetrics();
    
    addLogEntry(`> COMMAND ISSUED: ${cmd.toUpperCase()}`, "info");
  } catch(e) {
    addLogEntry(`Failed to execute command: ${cmd}`, "error");
  }
}

// WebSocket Logs
let ws;
function connectWebSocket() {
  ws = new WebSocket(WS_URL);
  
  ws.onopen = () => {
    console.log("WS Connected");
    addLogEntry("--- System Neural Link Established ---", "info");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if(data.message) {
         // Create visual string
         // time format e.g. 2026-04-09T14:45:00... => 14:45:00
         const timeMatch = data.time ? data.time.split('T')[1].substring(0,8) : "00:00:00";
         addLogEntry(`[${timeMatch}] ${data.message}`, data.level.toLowerCase());
      }
    } catch(e) {
      // If it's not valid json, just print it raw
      addLogEntry(event.data, "info");
    }
  };

  ws.onclose = () => {
    console.log("WS Disconnected. Reconnecting in 3s...");
    setTimeout(connectWebSocket, 3000);
  };
  
  ws.onerror = (err) => {
    ws.close();
  };
}

function addLogEntry(text, levelStr) {
  const div = document.createElement("div");
  div.className = `log-entry log-level-${levelStr}`;
  div.textContent = text;
  
  elements.terminalOutput.appendChild(div);
  
  // Keep maximum 100 lines for performance
  if (elements.terminalOutput.children.length > 100) {
    elements.terminalOutput.removeChild(elements.terminalOutput.firstChild);
  }
  
  // Auto scroll
  elements.terminalOutput.scrollTop = elements.terminalOutput.scrollHeight;
}

// Initialization
setInterval(fetchMetrics, 2000);
fetchMetrics();
connectWebSocket();

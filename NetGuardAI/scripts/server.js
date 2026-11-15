import { spawn } from "node:child_process";
import net from "node:net";
import { pythonExecutable } from "./runtime.js";

const HOST = "127.0.0.1";
const START_PORT = 8000;

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, HOST);
  });
}

async function choosePort(startPort = START_PORT, maxAttempts = 25) {
  for (let port = startPort; port < startPort + maxAttempts; port += 1) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }
  throw new Error(`No se encontró un puerto disponible desde ${startPort}.`);
}

const port = await choosePort();
const env = { ...process.env, PORT: String(port) };
const api = spawn(pythonExecutable, ["backend/server.py"], {
  cwd: process.cwd(),
  env,
  stdio: "inherit",
});

api.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 0);
});

process.on("SIGINT", () => api.kill("SIGINT"));
process.on("SIGTERM", () => api.kill("SIGTERM"));

import { spawn } from "node:child_process";
import net from "node:net";
import { resolve } from "node:path";
import { pythonExecutable } from "./runtime.js";

const API_HOST = "127.0.0.1";
const WEB_HOST = process.env.VITE_HOST || "127.0.0.1";
const START_PORT = 8000;

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, API_HOST);
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

const vite = spawn(
  process.execPath,
  [
    resolve(process.cwd(), "node_modules/vite/bin/vite.js"),
    "--host",
    WEB_HOST,
  ],
  {
    cwd: process.cwd(),
    env: {
      ...env,
      VITE_API_PORT: String(port),
      VITE_HOST: WEB_HOST,
    },
    stdio: "inherit",
  },
);

let shuttingDown = false;

const shutdown = (signal, exitCode = 0) => {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  process.exitCode = exitCode;
  api.kill(signal);
  vite.kill(signal);
};

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

api.on("exit", (code, signal) => {
  if (!shuttingDown) {
    shutdown(signal || "SIGTERM", code ?? 1);
  }
});

vite.on("exit", (code, signal) => {
  if (!shuttingDown) {
    shutdown(signal || "SIGTERM", code ?? 1);
  }
});

api.on("error", (error) => {
  console.error("No se pudo iniciar la API:", error.message);
  shutdown("SIGTERM", 1);
});

vite.on("error", (error) => {
  console.error("No se pudo iniciar Vite:", error.message);
  shutdown("SIGTERM", 1);
});

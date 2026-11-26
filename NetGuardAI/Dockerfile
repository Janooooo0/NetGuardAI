# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    WEB_PORT=8080 \
    PYTHON=/opt/venv/bin/python \
    NETGUARD_DB_PATH=/data/netguard.sqlite3 \
    NETGUARD_INVENTORY=/app/laptop.csv \
    NETGUARD_KEYS_DIR=/app/keys

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias del backend (psycopg2-binary, pysnmp, cryptography).
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

# Dependencias del frontend (vite incluido como dependencia de build).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build de producción del frontend (genera /app/dist).
RUN npm run build

# Servidor de producción: sirve /app/dist y hace proxy de /api al backend Python.
# Se genera aquí para no añadir archivos extra al repositorio.
RUN cat > /app/serve.mjs <<'SERVE_EOF'
import { spawn } from "node:child_process";
import http from "node:http";
import express from "express";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(fileURLToPath(import.meta.url));
const apiHost = process.env.API_HOST || "127.0.0.1";
const apiPort = Number(process.env.PORT || 8000);
const webHost = process.env.HOST || "0.0.0.0";
const webPort = Number(process.env.WEB_PORT || 8080);

const backend = spawn(process.env.PYTHON || "python3", ["backend/server.py"], {
  cwd: rootDir,
  env: { ...process.env, PORT: String(apiPort) },
  stdio: "inherit",
});

let shuttingDown = false;
let server = null;

function shutdown(signal, code = 0) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  process.exitCode = code;
  if (server) {
    server.close();
  }
  backend.kill(signal);
  setTimeout(() => process.exit(code), 5000).unref();
}

backend.on("exit", (code, signal) => {
  if (shuttingDown) {
    process.exit(process.exitCode ?? 0);
  }
  console.error(`El backend terminó inesperadamente (code=${code}, signal=${signal}).`);
  process.exit(code ?? 1);
});

backend.on("error", (error) => {
  console.error("No se pudo iniciar el backend:", error.message);
  process.exit(1);
});

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

const app = express();
app.disable("x-powered-by");

app.use("/api", (req, res) => {
  const proxyReq = http.request(
    {
      host: apiHost,
      port: apiPort,
      method: req.method,
      path: req.originalUrl,
      headers: { ...req.headers, host: `${apiHost}:${apiPort}` },
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );
  proxyReq.on("error", () => {
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    res.end(JSON.stringify({ error: "API no disponible." }));
  });
  req.pipe(proxyReq);
});

const distDir = join(rootDir, "dist");
app.use(express.static(distDir, { index: "index.html", maxAge: "1h" }));
app.use((req, res) => res.sendFile(join(distDir, "index.html")));

server = app.listen(webPort, webHost, () => {
  console.log(
    `NetGuard AI disponible en http://${webHost}:${webPort} (API en http://${apiHost}:${apiPort})`,
  );
});

server.on("error", (error) => {
  console.error("No se pudo iniciar el servidor web:", error.message);
  shutdown("SIGTERM", 1);
});
SERVE_EOF

RUN mkdir -p /data /app/keys

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+(process.env.WEB_PORT||8080)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "serve.mjs"]

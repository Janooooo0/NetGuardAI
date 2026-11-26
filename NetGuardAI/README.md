# 🛡️ NetGuard AI

Sistema para el monitoreo de redes empresariales que **detecta anomalías**, **analiza la degradación** de los equipos y **predice qué dispositivos están en riesgo** según la topología de la red.

> Curso **Computación en Red III**, sección B. Escuela Profesional de Ingeniería de Sistemas, UCSM. Versión **1.0.0**.
> Repositorio: <https://github.com/Janooooo0/NetGuardAI>

## Integrantes

- Lipa Lipa Luis Angel
- Rodriguez Zea Cristhian Jesus
- Morales Cárdenas Eduardo Gabriel
- Anco Sandoval Alejandro Augusto
- Loayza Mendoza Farid Jharen

## ¿Qué hace?

```
Inventario CSV → Recolección (ICMP / SNMPv3) → Base de datos → Detección de anomalías
   → Análisis de degradación → Evento de riesgo → Predicción por topología → Alerta → Historial
```

| Capacidad | Cómo está implementada | Archivo |
|---|---|---|
| Recolección ICMP | Ping periódico a los equipos autorizados (`PING_TARGETS`): latencia, pérdida y disponibilidad | `backend/ping_collector.py` |
| Recolección SNMPv3 | Consulta de interfaces (octetos, errores, descartes) con autenticación y cifrado (authPriv) | `backend/snmp_collector.py` |
| Detección de anomalías | Línea base adaptativa por interfaz (mediana). Un aumento de +50 %, +100 % o +200 % puntúa 25, 50 o 100; se exige un mínimo de +1 MB/min y la confirmación en 2 consultas seguidas. Una pérdida de ping ≥ 50 % también genera evento | `backend/server.py` |
| Degradación | Compara la medición más antigua con la más reciente (latencia ≥ +8 ms, pérdida ≥ +1,5 %, errores ≥ +3, disponibilidad ≥ −1 pp) | `backend/server.py` |
| **Predicción de riesgos** | Búsqueda en anchura (BFS) sobre el grafo de la red, hasta 3 saltos. Confianza = confianza del evento × 0,7^saltos. Marca los equipos como *potencialmente afectados*, nunca como comprometidos | `backend/risk_propagation.py` |
| Network Risk Index | Máximo puntaje de las anomalías de tráfico confirmadas en las últimas 24 h (0–100) | `backend/server.py` |
| Análisis con IA (opcional) | Un modelo de lenguaje local (Ollama, `qwen2.5:3b`) redacta el diagnóstico y las recomendaciones | `backend/server.py` |
| **Cifrado asimétrico** | Bóveda RSA-2048 (OAEP/SHA-256) + AES-256-GCM para guardar cifradas las credenciales (ver [Seguridad](#seguridad)) | `backend/crypto_vault.py` |
| Dashboard | React 18 + Vite: índice de riesgo, anomalías, degradación, predicciones e historial | `src/App.jsx` |

## Tecnologías

| Componente | Tecnología |
|---|---|
| Backend / API REST | Python 3.12, servidor HTTP de la biblioteca estándar (`http.server`) |
| Base de datos | SQLite (por defecto) o PostgreSQL 16 (`DATABASE_URL` + `psycopg2`) |
| Monitoreo de red | ICMP (ping del sistema operativo), SNMPv3 (`pysnmp`) |
| Seguridad | `cryptography` (RSA, AES-GCM), SNMPv3 authPriv |
| IA generativa | Ollama (opcional) |
| Frontend | React 18, Vite 6 |
| Despliegue | Node.js 20, Docker / Docker Compose (opcional) |

## Estructura

```
NetGuardAI/
├── backend/
│   ├── server.py              # API REST, base de datos, detección y dashboard
│   ├── ping_collector.py      # Recolector ICMP
│   ├── snmp_collector.py      # Recolector SNMPv3
│   ├── risk_propagation.py    # Predicción de riesgos por topología (BFS)
│   ├── crypto_vault.py        # Cifrado asimétrico (RSA + AES-GCM)
│   └── test_*.py              # Pruebas automatizadas
├── src/                       # Dashboard React
├── scripts/                   # Arranque conjunto API + Vite
├── demo/                      # Escenario simulado y validación en red real
├── evidencias/                # Capturas para el dossier
├── laptop.csv                 # Inventario de dispositivos
├── Dockerfile, docker-compose.yml
├── MANUAL_INSTALACION.md
└── requirements.txt, package.json
```

## Instalación rápida

Requisitos: Python 3.12, Node.js 20 y npm.

```bash
git clone https://github.com/Janooooo0/NetGuardAI.git
cd NetGuardAI/NetGuardAI
pip install -r requirements.txt
npm install
python backend/crypto_vault.py generar   # crea las llaves RSA en keys/ (solo la primera vez)
npm run dev
```

- Dashboard: <http://127.0.0.1:5173>
- API: <http://127.0.0.1:8000/api/health>

Con Docker:

```bash
docker compose up --build
```

Con Docker el dashboard queda en <http://localhost:8080>.

La guía completa está en [MANUAL_INSTALACION.md](MANUAL_INSTALACION.md).

## Inventario y topología (`laptop.csv`)

```csv
ip,name,type,uplink
192.168.10.1,Router-Core,Router,
192.168.10.2,Switch-Piso1,Switch,192.168.10.1
192.168.10.21,PC-Contabilidad,Computadora,192.168.10.2
```

- La columna `uplink`, opcional, indica a qué equipo se conecta cada dispositivo (por IP o nombre). Con ella se construye la topología que usa la predicción de riesgos.
- También se aceptan las columnas `mac` y los nombres alternativos `conectado_a` o `parent`.
- Solo se aceptan IPv4 privadas.

## Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `PORT`, `HOST` | Puerto y dirección de la API | `8000`, `127.0.0.1` |
| `DATABASE_URL` | Usa PostgreSQL en lugar de SQLite | (vacío → SQLite) |
| `NETGUARD_DB_PATH` | Ruta del archivo SQLite | `backend/netguard.sqlite3` |
| `NETGUARD_INVENTORY` | Ruta del inventario CSV | `laptop.csv` |
| `PING_TARGETS` | Lista JSON `[{"device_ip":"…","target_ip":"…"}]` | (vacío → ICMP desactivado) |
| `PING_INTERVAL_SECONDS` | Intervalo de ping (30–3600 s) | `60` |
| `SNMP_DEVICES` | Equipos a consultar por SNMPv3 | (vacío) |
| `SNMPV3_USERNAME`, `SNMPV3_AUTH_PASSWORD`, `SNMPV3_PRIV_PASSWORD` | Credenciales SNMPv3; las claves pueden ir **cifradas** (`enc:v1:…`) | — |
| `SNMPV3_AUTH_PROTOCOL`, `SNMPV3_PRIV_PROTOCOL` | `SHA` o `SHA-256`; `AES-128` | `SHA`, `AES-128` |
| `NETGUARD_KEYS_DIR`, `NETGUARD_KEY_PASSPHRASE` | Carpeta de las llaves RSA y frase opcional que protege la llave privada | `keys/` |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Servicio de IA local | `http://127.0.0.1:11434/api/chat`, `qwen2.5:3b` |

## API REST

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/dashboard` | Índice de riesgo, alertas, predicciones, degradación e inventario |
| GET | `/api/security/encryption` | Algoritmo y huella de la llave pública (no expone secretos) |
| POST | `/api/inventory/import` | Importa un inventario CSV |
| POST | `/api/snmp/poll` | Consulta SNMPv3 los equipos configurados |
| POST | `/api/ollama/analyze` | Análisis del dashboard con IA local |
| POST | `/api/security/analyze`, `/api/security/analyze-snmp` | Revisión de exposición de puertos (requiere confirmar autorización) |
| POST | `/api/network/check-ip` | Comprueba si una IP privada responde |

## Seguridad

1. **En tránsito (cifrado simétrico):** SNMPv3 en modo *authPriv*. Los mensajes se autentican con SHA o SHA-256 y se cifran con AES-128.
2. **En reposo (cifrado asimétrico):** las claves SNMP no se guardan en texto plano. Funciona como un candado:
   - **Llave pública** (`keys/netguard_public.pem`): cierra el candado, es decir, cifra. Puede compartirse.
   - **Llave privada** (`keys/netguard_private.pem`): es la única que lo abre, es decir, descifra. Se queda en el servidor, puede protegerse con frase y nunca se sube a GitHub.
   - Como RSA solo cifra datos cortos, se usa el esquema **híbrido** de TLS y PGP: el texto se cifra con una llave AES-256-GCM aleatoria, y esa llave se cifra con RSA-OAEP.

   ```bash
   python backend/crypto_vault.py cifrar "MiClaveSNMP123"
   # → enc:v1:eyJrIjogIm...   (pegar este valor en SNMPV3_AUTH_PASSWORD)
   ```

3. **Otras medidas:** solo se aceptan IPv4 privadas, el escaneo de puertos exige confirmar autorización, no hay credenciales en el repositorio (`.env`, `keys/` y `*.pem` están en `.gitignore`) y se usan consultas SQL parametrizadas.

## Pruebas y evidencias

```bash
python -m unittest backend.test_server backend.test_risk_propagation backend.test_crypto_vault
python demo/escenario_demo.py   # escenario controlado: 8 equipos y 2 incidentes inyectados
demo\iniciar_lab.cmd            # validación en red real con ping ICMP
```

Las capturas están en `evidencias/`.

## Licencia

Proyecto académico. Uso educativo.

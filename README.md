# 🛡️ NetGuard AI

Sistema inteligente para la detección de anomalías, análisis de degradación y predicción de riesgos en redes empresariales.

> Proyecto del curso **Computación en Red III**, Escuela Profesional de Ingeniería de Sistemas, UCSM, sección B. Versión 1.0.0.

## Descripción

NetGuard AI recopila información de los dispositivos de una red (PCs, switches, routers y servidores) y la analiza con aprendizaje automático para:

1. **Detectar actividad anómala:** aprende el comportamiento habitual de cada dispositivo y registra dispositivo, IP, fecha/hora, tipo de actividad, magnitud, nivel de confianza y nivel de riesgo.
2. **Analizar la degradación:** evalúa la tendencia histórica de latencia, pérdida de paquetes, errores y disponibilidad.
3. **Predecir riesgos:** identifica dispositivos *potencialmente afectados* por una anomalía según la topología, sin afirmar compromiso cuando no hay evidencia suficiente.

Todo queda registrado en base de datos y se muestra en un dashboard con el **Network Risk Index**, alertas y recomendaciones.

```
Datos → IA → Anomalía → Análisis → Riesgo → Predicción → Alerta → Historial
```

## Integrantes

- Anco Sandoval Alejandro Augusto
- Morales Cárdenas Eduardo Gabriel
- Lipa Lipa Luis Angel
- Loayza Mendoza Farid Jharen
- Rodriguez Zea Cristhian Jesus

## Tecnologías

| Componente | Tecnología |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| IA / ML | scikit-learn (Isolation Forest), pandas, NumPy, NetworkX |
| Base de datos | PostgreSQL 16, SQLAlchemy, Alembic |
| Frontend | React 18, Vite, Recharts |

## Requisitos

- Git 2.40 o superior
- Python 3.12
- Node.js 20 LTS y npm 10
- PostgreSQL 16
- 4 GB de RAM y 3 GB de disco libres
- Puertos libres: `8000` (API), `5173` (frontend), `5432` (PostgreSQL)

## Estructura del repositorio

```
NN_NetGuardAI/
├── backend/        # API, módulos de IA y migraciones
├── frontend/       # Dashboard web
├── scripts/        # Datos de demostración y entrenamiento
├── docs/           # Diagrama de arquitectura
├── .env.example    # Ejemplo de variables de entorno
└── README.md
```

## Instalación y ejecución

### 1. Clonar el proyecto

```bash
git clone https://github.com/[usuario]/[NN]_NetGuardAI.git
cd [NN]_NetGuardAI
```

### 2. Crear la base de datos

```bash
psql -U postgres -c "CREATE USER netguard_user WITH PASSWORD 'defina_su_clave';"
psql -U postgres -c "CREATE DATABASE netguard OWNER netguard_user;"
```

### 3. Configurar variables de entorno

```bash
cp .env.example backend/.env      # Windows: copy .env.example backend\.env
```

Edite `backend/.env` con sus valores. **No suba este archivo a GitHub.**

| Variable | Descripción | Ejemplo |
|---|---|---|
| `DB_HOST` | Servidor de BD | `localhost` |
| `DB_PORT` | Puerto de BD | `5432` |
| `DB_NAME` | Nombre de la BD | `netguard` |
| `DB_USER` | Usuario de BD | `netguard_user` |
| `DB_PASSWORD` | Clave del usuario | `cambiar_esto` |
| `ANOMALY_CONTAMINATION` | Proporción esperada de anomalías | `0.05` |
| `COLLECTOR_MODE` | `simulator` o `snmp` | `simulator` |

### 4. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
python scripts/seed_demo_data.py
python scripts/train_model.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

La API queda en `http://localhost:8000` y su documentación en `http://localhost:8000/docs`.

### 5. Frontend (en otra terminal)

```bash
cd frontend
npm install
npm run dev
```

El dashboard queda en `http://localhost:5173`.

## Verificación

1. `curl http://localhost:8000/health` debe responder `{"status":"ok"}`.
2. Abrir `http://localhost:5173`: se muestra el Network Risk Index y los contadores de anomalías, degradación y riesgos críticos.
3. La lista de alertas incluye la anomalía de demostración con dispositivo, IP, fecha/hora, magnitud, confianza y riesgo.
4. Al abrir un dispositivo se ve su tendencia de degradación y los dispositivos potencialmente afectados.

## Seguridad

Este repositorio no contiene contraseñas, tokens, certificados ni claves privadas. Toda credencial se define localmente en `.env`, que está excluido mediante `.gitignore`.

## Licencia

Proyecto académico. Uso educativo.

# NetGuard AI

Prototipo local de monitoreo de red con dashboard React, API Python y base de
datos SQLite. Todos los dispositivos, métricas y eventos iniciales son
sintéticos; este proyecto todavía no recopila datos de una red real.

## Requisitos

- Node.js 20 o posterior
- Python 3.10 o posterior

## Ejecutar en desarrollo

Instala las dependencias de React:

```bash
npm install
```

Inicia la API y el frontend juntos:

```bash
npm run dev
```

Abre la dirección que muestra Vite (normalmente `http://127.0.0.1:5173`). El
comando inicia también la API, disponible en `http://127.0.0.1:8000`, y Vite
reenvía las solicitudes `/api` durante el desarrollo. Mantén esa terminal
abierta mientras usas el dashboard. Para iniciar solo la API, ejecuta
`npm run server`.

El botón **Simular observación** crea una métrica sintética, compara su valor con
el historial del dispositivo, registra una anomalía y genera posibles
dispositivos afectados según la topología de demostración. La información se
guarda en `backend/netguard.sqlite3`.

## Qué representa este prototipo

- Métricas: latencia, pérdida de paquetes, errores, disponibilidad y tráfico.
- Detección demostrativa: línea base histórica y umbrales estadísticos sencillos;
  no es un modelo de aprendizaje automático entrenado.
- Network Risk Index: 75% del promedio de puntuaciones de anomalías de las
  últimas 24 horas, más 8 puntos por cada dispositivo con una tendencia de
  degradación, limitado a 100.
- Predicción: dispositivos a uno o dos saltos en la topología. Es una sugerencia
  para investigar, no evidencia de compromiso.
- Persistencia: SQLite local; el historial y las observaciones simuladas
  permanecen entre reinicios.

## Pruebas

```bash
npm run test:api
npm run build
```

La integración con equipos reales requerirá definir una fuente autorizada de
telemetría, como SNMP, NetFlow/sFlow/IPFIX, agentes o métricas de los propios
dispositivos, además de credenciales, retención y límites de recolección. El
prototipo no escanea ni accede a equipos de la red.

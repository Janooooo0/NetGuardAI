## NetGuard AI v1.0.0

Primera versión estable del sistema de detección de anomalías, análisis de degradación y predicción de riesgos en redes empresariales.
Curso Computación en Red III, sección B, UCSM.

### Funcionalidades
- Recolección ICMP (Windows y Linux) y SNMPv3 cifrado (authPriv: SHA + AES-128).
- Detección de anomalías con una línea base adaptativa por interfaz; una anomalía se confirma tras 2 sondeos seguidos.
- Análisis de degradación: latencia, pérdida de paquetes, errores y disponibilidad.
- **Predicción de riesgos por topología:** recorre la red en anchura (BFS) hasta 3 saltos y marca los dispositivos potencialmente afectados.
- **Cifrado asimétrico:** bóveda RSA-2048 + AES-256-GCM para las credenciales.
- Network Risk Index, alertas, historial y dashboard en React.
- Análisis opcional con IA local (Ollama).
- Despliegue con Docker (`docker compose up --build`, puerto 8080).

### Validación
- 51 pruebas automatizadas aprobadas.
- Escenario controlado de 8 dispositivos con 2 incidentes inyectados: ambos fueron detectados.
- Ejecución en una red real con ping ICMP: detectó la caída de un host y generó la predicción de los equipos en riesgo. Con esto el proyecto alcanza **TRL 5**.

### Documentación
- `README.md`
- `NetGuardAI/MANUAL_INSTALACION.md`
- `docs/Dossier_Tecnologico_NetGuardAI_v1.0.0.pdf`

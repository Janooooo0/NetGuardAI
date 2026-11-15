import { useCallback, useEffect, useState } from "react";

const navigation = [
  {
    title: "PRINCIPAL",
    links: [
      { href: "#dashboard", icon: "▦", label: "Dashboard" },
      { href: "#dispositivos", icon: "▣", label: "Dispositivos" },
      { href: "#anomalias", icon: "⌁", label: "Anomalías" },
    ],
  },
  {
    title: "ANÁLISIS INTELIGENTE",
    links: [
      { href: "#degradacion", icon: "◷", label: "Degradación" },
      { href: "#predicciones", icon: "⚠", label: "Predicción de riesgos" },
    ],
  },
  {
    title: "SISTEMA",
    links: [
      { href: "#historial", icon: "▤", label: "Historial de eventos" },
      { href: "#configuracion", icon: "⚙", label: "Configuración" },
    ],
  },
];

const riskClass = {
  Alto: "high",
  Medio: "medium",
  Bajo: "normal",
};

async function requestJson(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error(
      "No se pudo conectar con la API. Inicia el proyecto con «npm run dev» y vuelve a intentarlo.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("La API respondió con un formato no válido. Revisa la terminal.");
  }
  if (!response.ok) {
    throw new Error(data.error || "No fue posible completar la solicitud.");
  }
  return data;
}

function Sidebar({ activeLink, onNavigate }) {
  return (
    <aside className="sidebar">
      <a className="logo" href="#dashboard" onClick={() => onNavigate("#dashboard")}>
        NetGuard <span>AI</span>
      </a>
      {navigation.map((group) => (
        <nav className="nav-group" key={group.title} aria-label={group.title}>
          <h2>{group.title}</h2>
          {group.links.map(({ href, icon, label }) => (
            <a
              className={`nav-link${activeLink === href ? " active" : ""}`}
              href={href}
              key={href}
              onClick={() => onNavigate(href)}
            >
              <span className="nav-icon" aria-hidden="true">
                {icon}
              </span>
              {label}
            </a>
          ))}
        </nav>
      ))}
    </aside>
  );
}

function PanelHeader({ title, note }) {
  return (
    <div className="panel-header">
      <h2>{title}</h2>
      {note && <span>{note}</span>}
    </div>
  );
}

function Badge({ children, variant }) {
  return <span className={`badge ${variant}`}>{children}</span>;
}

function formatTime(value) {
  return new Intl.DateTimeFormat("es", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function ActivityChart({ traffic }) {
  const values = traffic.map((point) => point.value);
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const spread = max - min || max;

  return (
    <>
      <div
        className="chart"
        role="img"
        aria-label="Actividad promedio de tráfico de dispositivos en el historial"
      >
        {traffic.map((point, index) => {
          const height = 18 + ((point.value - min) / spread) * 82;
          return (
            <div
              className="bar"
              key={`${point.label}-${index}`}
              style={{ height: `${height}%` }}
              title={`${point.value} MB/min · ${point.label}`}
            />
          );
        })}
      </div>
      <div className="chart-labels" aria-hidden="true">
        {traffic.map((point, index) =>
          index % 2 === 0 || index === traffic.length - 1 ? (
            <span key={`${point.label}-${index}`}>{point.label}</span>
          ) : null,
        )}
      </div>
    </>
  );
}

function AlertsTable({ alerts }) {
  if (alerts.length === 0) {
    return <p className="empty-state">Todavía no hay anomalías registradas.</p>;
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Dispositivo</th>
            <th>Actividad</th>
            <th>Magnitud</th>
            <th>Fecha y hora</th>
            <th>Riesgo</th>
            <th>Confianza</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => (
            <tr key={alert.id}>
              <td>
                <span className="device">{alert.device}</span>
                <span className="cell-secondary">{alert.ip}</span>
              </td>
              <td>
                {alert.activity}
                <span className="cell-secondary">{alert.status}</span>
                <span className="cell-secondary">
                  Recomendación: {alert.recommendation}
                </span>
              </td>
              <td>{alert.magnitude}</td>
              <td>{formatTime(alert.capturedAt)}</td>
              <td>
                <Badge variant={riskClass[alert.risk]}>{alert.risk}</Badge>
              </td>
              <td>{Math.round(alert.confidence * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DevicesTable({ devices }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Dispositivo</th>
            <th>Tipo</th>
            <th>Latencia</th>
            <th>Pérdida</th>
            <th>Errores</th>
            <th>Disponibilidad</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((device) => (
            <tr key={device.name}>
              <td>
                <span className="device">{device.name}</span>
                <span className="cell-secondary">{device.ip}</span>
              </td>
              <td>{device.type}</td>
              <td>{device.latencyMs} ms</td>
              <td>{device.packetLossPct}%</td>
              <td>{device.errors}</td>
              <td>{device.availabilityPct}%</td>
              <td>
                <Badge variant={device.statusClass}>{device.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function App() {
  const [activeLink, setActiveLink] = useState(
    window.location.hash || "#dashboard",
  );
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadDashboard = useCallback(async () => {
    const data = await requestJson("/api/dashboard");
    setDashboard(data);
    setError("");
  }, []);

  useEffect(() => {
    const updateActiveLink = () => {
      setActiveLink(window.location.hash || "#dashboard");
    };
    window.addEventListener("hashchange", updateActiveLink);
    loadDashboard()
      .catch((requestError) => {
        setError(requestError.message);
      })
      .finally(() => setLoading(false));
    return () => window.removeEventListener("hashchange", updateActiveLink);
  }, [loadDashboard]);

  async function handleRefresh() {
    setBusy(true);
    setNotice("");
    try {
      await loadDashboard();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  async function handleSimulate() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const event = await requestJson("/api/simulate", { method: "POST" });
      await loadDashboard();
      setNotice(
        `Observación sintética registrada en ${event.device}: ${event.activity}.`,
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  if (loading && !dashboard) {
    return (
      <main className="standalone-message" aria-live="polite">
        <h1>Conectando con NetGuard AI…</h1>
      </main>
    );
  }

  if (!dashboard) {
    return (
      <main className="standalone-message" role="alert">
        <h1>No se pudo cargar el dashboard</h1>
        <p>{error}</p>
        <p>
          Inicia la API con <code>npm run server</code> y vuelve a intentarlo.
        </p>
        <button className="button" onClick={handleRefresh} disabled={busy}>
          Reintentar
        </button>
      </main>
    );
  }

  const latestAlert = dashboard.alerts[0];
  const maxTraffic = Math.max(...dashboard.traffic.map((point) => point.value), 0);

  return (
    <div className="app-shell">
      <Sidebar activeLink={activeLink} onNavigate={setActiveLink} />
      <main id="dashboard">
        <header className="page-header">
          <div>
            <h1>Dashboard de seguridad</h1>
            <p>Monitoreo inteligente de la red empresarial</p>
          </div>
          <div className="header-actions">
            <div className="system-status">
              <span aria-hidden="true">●</span> API activa · datos sintéticos
            </div>
            <button
              className="button button-secondary"
              onClick={handleRefresh}
              disabled={busy}
            >
              Actualizar
            </button>
            <button
              className="button"
              onClick={handleSimulate}
              disabled={busy}
            >
              {busy ? "Procesando…" : "Simular observación"}
            </button>
          </div>
        </header>

        {(error || notice) && (
          <div className={`notice${error ? " notice-error" : ""}`} role="status">
            <span>{error || notice}</span>
            {error && (
              <button className="text-button" onClick={handleRefresh}>
                Reintentar
              </button>
            )}
          </div>
        )}

        <div className="pipeline" aria-label="Flujo de análisis">
          <span>Datos sintéticos</span>
          <b aria-hidden="true">→</b>
          <span>Línea base</span>
          <b aria-hidden="true">→</b>
          <span>Anomalía</span>
          <b aria-hidden="true">→</b>
          <span>Análisis</span>
          <b aria-hidden="true">→</b>
          <span>Riesgo</span>
          <b aria-hidden="true">→</b>
          <span>Predicción topológica</span>
          <b aria-hidden="true">→</b>
          <span>Alerta e historial</span>
        </div>

        <h2 className="section-title">Resumen de la red</h2>
        <section className="cards" aria-label="Resumen de la red">
          <article className="card">
            <p>Dispositivos monitoreados</p>
            <h3 className="blue">{dashboard.summary.monitoredDevices}</h3>
            <span className="change">Inventario de demostración</span>
          </article>
          <article className="card">
            <p>Anomalías en las últimas 24 h</p>
            <h3 className="red">{dashboard.summary.anomalies}</h3>
            <span className="change">Eventos guardados en el historial</span>
          </article>
          <article className="card">
            <p>Dispositivos con tendencia de degradación</p>
            <h3 className="yellow">{dashboard.summary.degradingDevices}</h3>
            <span className="change">Según métricas históricas</span>
          </article>
          <article className="card">
            <p>Alertas de riesgo alto</p>
            <h3 className="red">{dashboard.summary.criticalRisks}</h3>
            <span className="change">No equivale a compromiso confirmado</span>
          </article>
        </section>

        <section className="columns">
          <article className="panel">
            <PanelHeader title="Actividad de la red" note="Tráfico promedio · MB/min" />
            {dashboard.traffic.length > 0 ? (
              <ActivityChart traffic={dashboard.traffic} />
            ) : (
              <p className="empty-state">No hay métricas históricas disponibles.</p>
            )}
            <p className="chart-summary">
              Pico reciente: {maxTraffic} MB/min · Solo datos sintéticos
            </p>
          </article>

          <article
            className={`panel risk-panel risk-${dashboard.riskLevel.toLowerCase()}`}
            id="riesgos"
          >
            <PanelHeader title="Network Risk Index" note="Indicador demostrativo" />
            <div className="risk-score">{dashboard.riskIndex}/100</div>
            <p className="risk-level">
              ● Nivel de riesgo {dashboard.riskLevel.toLowerCase()}
            </p>
            <div
              className="risk-progress"
              role="progressbar"
              aria-label="Network Risk Index"
              aria-valuenow={dashboard.riskIndex}
              aria-valuemin="0"
              aria-valuemax="100"
            >
              <span style={{ width: `${dashboard.riskIndex}%` }} />
            </div>
            <p className="muted-copy">{dashboard.riskExplanation}</p>
          </article>
        </section>

        <section className="panel" id="anomalias">
          <PanelHeader title="Alertas recientes" note="Persistidas en el historial local" />
          <AlertsTable alerts={dashboard.alerts.slice(0, 8)} />
        </section>

        <section className="columns">
          <article className="panel" id="dispositivos">
            <PanelHeader title="Estado de dispositivos" note="Métricas más recientes" />
            <DevicesTable devices={dashboard.devices} />
          </article>

          <article className="panel" id="degradacion">
            <PanelHeader title="Análisis de degradación" note="Comparación con historial" />
            {dashboard.degradations.length === 0 ? (
              <p className="empty-state">No se detectan tendencias de degradación.</p>
            ) : (
              dashboard.degradations.map((item) => (
                <div className="risk-box" key={item.device}>
                  <h3>{item.device}</h3>
                  <ul className="change-list">
                    {item.changes.map((change) => (
                      <li key={change.metric}>
                        {change.metric}: +{change.change} {change.unit}
                      </li>
                    ))}
                  </ul>
                  <p className="recommendation">{item.recommendation}</p>
                </div>
              ))
            )}
          </article>
        </section>

        <section className="panel" id="historial">
          <PanelHeader title="Historial de eventos" note="Eventos registrados en SQLite" />
          {dashboard.alerts.length === 0 ? (
            <p className="empty-state">No hay eventos en el historial.</p>
          ) : (
            <ol className="history-list">
              {dashboard.alerts.slice(0, 12).map((alert) => (
                <li key={alert.id}>
                  <time dateTime={alert.capturedAt}>{formatTime(alert.capturedAt)}</time>
                  <span className="device">{alert.device}</span>
                  <span>{alert.activity}</span>
                  <Badge variant={riskClass[alert.risk]}>{alert.risk}</Badge>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="panel" id="predicciones">
          <PanelHeader
            title="Predicción por topología"
            note="Dispositivos potencialmente afectados; no confirma compromiso"
          />
          {!latestAlert || latestAlert.predictions.length === 0 ? (
            <p className="empty-state">
              No hay predicciones topológicas para los eventos recientes.
            </p>
          ) : (
            <>
              <p className="prediction-origin">
                Evento de origen: <strong>{latestAlert.device}</strong> ·{" "}
                {latestAlert.activity}
              </p>
              <div className="prediction-grid">
                {latestAlert.predictions.map((prediction) => (
                  <article
                    className="prediction-card"
                    key={`${latestAlert.id}-${prediction.device}`}
                  >
                    <strong>{prediction.device}</strong>
                    <span>{prediction.hops} salto(s) en la topología</span>
                    <span>
                      Confianza topológica: {Math.round(prediction.confidence * 100)}%
                    </span>
                    <p>{prediction.reason}</p>
                  </article>
                ))}
              </div>
              <p className="muted-copy">
                La topología solo sugiere qué dispositivos evaluar. No hay
                evidencia suficiente para afirmar que estén comprometidos.
              </p>
            </>
          )}
        </section>

        <section className="panel" id="configuracion">
          <PanelHeader title="Configuración del sistema" />
          <p className="configuration-copy">
            Estado: prototipo local con observaciones sintéticas.
            <br />
            Detección: línea base y reglas estadísticas demostrativas (no es un
            modelo de aprendizaje automático entrenado).
            <br />
            Persistencia: SQLite local.
            <br />
            Recolección de equipos reales: pendiente de integración y autorización.
          </p>
        </section>

        <footer>
          NetGuard AI © 2026 | Prototipo de análisis de redes empresariales
        </footer>
      </main>
    </div>
  );
}

export default App;

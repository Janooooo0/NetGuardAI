import { useCallback, useEffect, useRef, useState } from "react";

const navigation = [
  {
    title: "PRINCIPAL",
    links: [
      { href: "#dashboard", icon: "▦", label: "Dashboard" },
      { href: "#dispositivos", icon: "▣", label: "Dispositivos" },
      { href: "#inventario-lan", icon: "⌂", label: "Inventario LAN" },
      { href: "#anomalias", icon: "⌁", label: "Anomalías" },
    ],
  },
  {
    title: "REVISIÓN DE EQUIPOS",
    links: [
      { href: "#ollama", icon: "1", label: "CSV · laptop.csv" },
      { href: "#escaneo", icon: "2", label: "IP manual" },
      { href: "#snmp", icon: "3", label: "SNMPv3" },
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

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${days} d ${hours} h ${minutes} min`;
}

function InterfaceTable({ interfaces }) {
  const statuses = {
    1: "Activa",
    2: "Inactiva",
    3: "Prueba",
    4: "Desconocida",
    5: "Dormida",
    6: "No disponible",
    7: "Enlace inferior caído",
  };
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Interfaz</th>
            <th>Estado</th>
            <th>Entrada (MB/min)</th>
            <th>Salida (MB/min)</th>
            <th>Total (MB/min)</th>
            <th>Errores entrada</th>
            <th>Errores salida</th>
            <th>Descartes entrada</th>
            <th>Descartes salida</th>
          </tr>
        </thead>
        <tbody>
          {interfaces.map((item) => (
            <tr key={item.index}>
              <td>{item.name}</td>
              <td>{statuses[item.status] || "Sin dato"}</td>
              <td>
                {item.inTrafficMbPerMinute == null
                  ? "Esperando otra lectura"
                  : item.inTrafficMbPerMinute}
              </td>
              <td>
                {item.outTrafficMbPerMinute == null
                  ? "Esperando otra lectura"
                  : item.outTrafficMbPerMinute}
              </td>
              <td>
                {item.trafficMbPerMinute == null
                  ? "Esperando otra lectura"
                  : item.trafficMbPerMinute}
              </td>
              <td>{item.inErrorsSinceLast ?? "—"}</td>
              <td>{item.outErrorsSinceLast ?? "—"}</td>
              <td>{item.inDiscardsSinceLast ?? "—"}</td>
              <td>{item.outDiscardsSinceLast ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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
                {device.source === "ICMP" && (
                  <span className="cell-secondary">
                    Ping {device.probesReceived}/{device.probesSent} a{" "}
                    {device.pingTarget} · {formatTime(device.capturedAt)}
                  </span>
                )}
              </td>
              <td>{device.type}</td>
              <td>{device.latencyMs == null ? "—" : `${device.latencyMs} ms`}</td>
              <td>
                {device.packetLossPct == null ? "—" : `${device.packetLossPct}%`}
              </td>
              <td>{device.errors ?? "—"}</td>
              <td>
                {device.availabilityPct == null
                  ? "—"
                  : `${device.availabilityPct}%`}
              </td>
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

function NetworkInventoryTable({ devices }) {
  if (devices.length === 0) {
    return (
      <p className="empty-state">
        Aún no hay inventario importado del router o servidor DHCP.
      </p>
    );
  }
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Dirección IP</th>
            <th>Dirección MAC</th>
            <th>Tipo</th>
            <th>Importado</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((device) => (
            <tr key={device.ip}>
              <td>{device.name}</td>
              <td>{device.ip}</td>
              <td>{device.mac || "—"}</td>
              <td>{device.type}</td>
              <td>{formatTime(device.importedAt)}</td>
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
  const [ollamaAnalysis, setOllamaAnalysis] = useState("");
  const [ollamaModel, setOllamaModel] = useState("");
  const [scanIp, setScanIp] = useState("");
  const [scanAuthorized, setScanAuthorized] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [ipReachability, setIpReachability] = useState(null);
  const [deviceAnalysis, setDeviceAnalysis] = useState("");
  const [snmpExposureAnalysis, setSnmpExposureAnalysis] = useState(null);
  const [snmpScanAuthorized, setSnmpScanAuthorized] = useState(false);
  const inventoryFileInput = useRef(null);

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
    const refreshTimer = window.setInterval(() => {
      loadDashboard().catch((requestError) => {
        setError(requestError.message);
      });
    }, 60_000);
    return () => {
      window.removeEventListener("hashchange", updateActiveLink);
      window.clearInterval(refreshTimer);
    };
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

  async function handleOllamaAnalysis() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await requestJson("/api/ollama/analyze", {
        method: "POST",
      });
      setOllamaAnalysis(result.analysis);
      setOllamaModel(result.model);
      setNotice("Análisis generado con Ollama.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSnmpPoll() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await requestJson("/api/snmp/poll", { method: "POST" });
      await loadDashboard();
      const failures = result.results.filter((item) => item.error);
      if (failures.length > 0) {
        setError(
          `Lecturas guardadas: ${result.saved}. Fallaron: ${failures
            .map((item) => `${item.name} (${item.error})`)
            .join("; ")}`,
        );
      } else {
        setNotice(`Lectura SNMPv3 completada en ${result.saved} equipos.`);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  async function handleSnmpExposureAnalysis() {
    setBusy(true);
    setError("");
    setNotice("");
    setSnmpExposureAnalysis(null);
    try {
      const result = await requestJson("/api/security/analyze-snmp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ authorized: snmpScanAuthorized }),
      });
      setSnmpExposureAnalysis(result);
      setNotice(
        `IA analizó la exposición de ${result.deviceResults.length} equipos SNMPv3.`,
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleInventoryImport(event) {
    event.preventDefault();
    const file = inventoryFileInput.current?.files?.[0];
    if (!file) {
      setError("Selecciona el CSV exportado desde el router o servidor DHCP.");
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      const csv = await file.text();
      const result = await requestJson("/api/inventory/import", {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: csv,
      });
      await loadDashboard();
      setNotice(`Se importaron ${result.imported} equipos del inventario DHCP.`);
      inventoryFileInput.current.value = "";
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSecurityScan(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setScanResult(null);
    setDeviceAnalysis("");
    try {
      const result = await requestJson("/api/security/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip: scanIp.trim(), authorized: scanAuthorized }),
      });
      setScanResult(result);
      setNotice(`Comprobación de exposición completada para ${result.ip}.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleIpReachabilityCheck() {
    setBusy(true);
    setError("");
    setNotice("");
    setIpReachability(null);
    try {
      const result = await requestJson("/api/network/check-ip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip: scanIp.trim(), authorized: scanAuthorized }),
      });
      setIpReachability(result);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeviceAnalysis() {
    if (!scanResult) {
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    setDeviceAnalysis("");
    try {
      const result = await requestJson("/api/security/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip: scanResult.ip,
          authorized: scanAuthorized,
        }),
      });
      setScanResult(result.scan);
      setDeviceAnalysis(result.analysis);
      setNotice(`IA completó el análisis preliminar de ${result.scan.ip}.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
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
              <span aria-hidden="true">●</span> API activa · laptop.csv
            </div>
            <button
              className="button button-secondary"
              onClick={handleRefresh}
              disabled={busy}
            >
              Actualizar
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

        <h2 className="section-title">Resumen de la red</h2>
        <section className="cards" aria-label="Resumen de la red">
          <article className="card">
            <p>Dispositivos monitoreados</p>
            <h3 className="blue">{dashboard.summary.monitoredDevices}</h3>
            <span className="change">Registros de laptop.csv</span>
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
              {dashboard.traffic.length > 0
                ? `Pico reciente: ${maxTraffic} MB/min · Datos guardados`
                : "No hay datos de tráfico guardados para los equipos del CSV."}
            </p>
          </article>

          <article
            className={`panel risk-panel${
              dashboard.riskIndex == null
                ? " risk-no-data"
                : ` risk-${dashboard.riskLevel.toLowerCase()}`
            }`}
            id="riesgos"
          >
            <PanelHeader title="Network Risk Index" note="Anomalías de tráfico SNMP" />
            <div className="risk-score">
              {dashboard.riskIndex == null
                ? "Sin datos"
                : `${dashboard.riskIndex}/100`}
            </div>
            <p className="risk-level">
              {dashboard.riskIndex == null
                ? "Faltan lecturas SNMP comparables"
                : `● Nivel de riesgo ${dashboard.riskLevel.toLowerCase()}`}
            </p>
            {dashboard.riskIndex != null && (
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
            )}
            <p className="muted-copy">{dashboard.riskExplanation}</p>
            <p className="chart-summary">
              SNMP reciente: {dashboard.riskCoverage.devicesWithRecentSnmp}/
              {dashboard.riskCoverage.devicesInInventory} dispositivos ·{" "}
              {dashboard.riskCoverage.interfacesEvaluated} interfaces comparables
            </p>
            {dashboard.riskFindings.length > 0 && (
              <ul className="risk-findings">
                {dashboard.riskFindings.map((finding) => (
                  <li key={`${finding.ip}-${finding.interface}`}>
                    <strong>{finding.device}</strong> · {finding.interface}: aumento{" "}
                    {finding.increasePct}% sobre la línea base (
                    {finding.riskScore} puntos)
                  </li>
                ))}
              </ul>
            )}
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

        <section className="panel" id="inventario-lan">
          <PanelHeader
            title="Inventario de red (router/DHCP)"
            note="Importación manual · sin sondeo activo"
          />
          <p className="muted-copy">
            Exporta la lista de concesiones DHCP de tu router o servidor e
            impórtala aquí para agregar datos MAC a las IP ya incluidas en
            <code> laptop.csv</code>. Este panel no agrega otros equipos a la
            lista principal.
          </p>
          <form className="inventory-import" onSubmit={handleInventoryImport}>
            <label htmlFor="inventory-csv">
              Archivo CSV (columnas: <code>ip</code>, opcionalmente{" "}
              <code>name</code>, <code>mac</code>, <code>type</code>)
            </label>
            <input
              id="inventory-csv"
              ref={inventoryFileInput}
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
            />
            <button className="button" type="submit" disabled={busy}>
              {busy ? "Importando…" : "Importar inventario"}
            </button>
          </form>
          <NetworkInventoryTable devices={dashboard.networkInventory} />
        </section>

        <section className="panel" id="ollama">
          <PanelHeader
            title="1. Análisis de dispositivos desde CSV"
            note={ollamaModel ? `Modelo ${ollamaModel}` : "No solicitado"}
          />
          <p className="muted-copy">
            Analiza los equipos del archivo <code>laptop.csv</code> y los
            correlaciona con los datos disponibles. Este análisis orienta la
            revisión de riesgo; no confirma vulnerabilidades.
          </p>
          <button
            className="button button-secondary"
            onClick={handleOllamaAnalysis}
            disabled={busy}
          >
            {busy ? "Procesando…" : "Analizar laptop.csv"}
          </button>
          {ollamaAnalysis ? (
            <p className="ollama-analysis">{ollamaAnalysis}</p>
          ) : (
            <p className="empty-state">
              Ejecuta primero el análisis del CSV para revisar los equipos y
              correlacionarlos con métricas y alertas disponibles.
            </p>
          )}
        </section>

        <section className="panel" id="escaneo">
          <PanelHeader
            title="2. Comprobación manual por IP"
            note="Una IP privada · comprobaciones TCP limitadas"
          />
          <p className="muted-copy">
            Revisa si puertos asociados a servicios comunes son accesibles en un
            dispositivo de tu red privada. No intenta iniciar sesión, explotar
            servicios ni determinar versiones; un puerto accesible no confirma
            por sí solo una vulnerabilidad.
          </p>
          <form className="security-scan-form" onSubmit={handleSecurityScan}>
            <label htmlFor="scan-ip">Dirección IPv4 del dispositivo</label>
            <div className="scan-input-row">
              <input
                id="scan-ip"
                type="text"
                inputMode="decimal"
                autoComplete="off"
                placeholder="192.168.1.20"
                value={scanIp}
                onChange={(event) => {
                  setScanIp(event.target.value);
                  setScanResult(null);
                  setIpReachability(null);
                  setDeviceAnalysis("");
                }}
                required
                disabled={busy}
              />
              <button
                className="button"
                type="submit"
                disabled={busy || !scanAuthorized}
              >
                {busy ? "Comprobando…" : "Comprobar exposición"}
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={handleIpReachabilityCheck}
                disabled={busy || !scanAuthorized || !scanIp.trim()}
              >
                {busy ? "Comprobando…" : "Comprobar si responde"}
              </button>
            </div>
            <label className="authorization-check">
              <input
                type="checkbox"
                checked={scanAuthorized}
                onChange={(event) => setScanAuthorized(event.target.checked)}
                disabled={busy}
              />
              Confirmo que soy responsable del dispositivo o tengo autorización
              para evaluarlo.
            </label>
          </form>
          {ipReachability && (
            <p className="availability-result" role="status">
              <Badge variant={ipReachability.reachable ? "normal" : "medium"}>
                {ipReachability.reachable ? "Responde" : "Sin respuesta"}
              </Badge>{" "}
              {ipReachability.reachable
                ? `${ipReachability.ip} respondió a la comprobación ICMP.`
                : `${ipReachability.ip} no respondió. ${ipReachability.note}`}
            </p>
          )}
          {scanResult && (
            <div className="scan-results" aria-live="polite">
              <div className="panel-header">
                <h3>Resultado para {scanResult.ip}</h3>
                <span>{formatTime(scanResult.checkedAt)}</span>
              </div>
              {scanResult.exposedServices.length === 0 ? (
                <p className="empty-state">
                  No se detectaron servicios accesibles en los puertos
                  comprobados. Esto no garantiza que el dispositivo esté libre
                  de vulnerabilidades.
                </p>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Servicio</th>
                        <th>Puerto</th>
                        <th>Exposición</th>
                        <th>Recomendación</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scanResult.exposedServices.map((service) => (
                        <tr key={service.port}>
                          <td>{service.service}</td>
                          <td>{service.port}</td>
                          <td>
                            <Badge variant={riskClass[service.severity]}>
                              {service.severity}
                            </Badge>
                          </td>
                          <td>{service.recommendation}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="chart-summary">{scanResult.note}</p>
              <p className="muted-copy">
                La IA volverá a comprobar los puertos de esta IP y explicará los
                indicios observados. No puede confirmar CVE ni vulnerabilidades
                con esta comprobación limitada.
              </p>
              <button
                className="button button-secondary"
                onClick={handleDeviceAnalysis}
                disabled={busy || !scanAuthorized}
              >
                {busy ? "Analizando…" : "Recomprobar y analizar con IA"}
              </button>
              {deviceAnalysis && (
                <p className="ollama-analysis">{deviceAnalysis}</p>
              )}
            </div>
          )}
        </section>

        <section className="panel" id="snmp">
          <PanelHeader
            title="3. Consulta de dispositivos mediante SNMPv3"
            note="Consultas manuales · authPriv · solo lectura"
          />
          <button
            className="button button-secondary"
            onClick={handleSnmpPoll}
            disabled={busy}
          >
            {busy ? "Procesando…" : "Consultar SNMPv3"}
          </button>
          {dashboard.snmpDevices.length === 0 ? (
            <p className="empty-state">
              Aún no hay lecturas. Configura al menos un equipo y usa el botón
              “Consultar SNMPv3”. El tráfico por minuto aparecerá después de
              una segunda lectura.
            </p>
          ) : (
            dashboard.snmpDevices.map((device) => (
              <article className="risk-box" key={device.ip}>
                <h3>{device.name}</h3>
                <p className="configuration-copy">
                  {device.ip} · Uptime: {formatUptime(device.uptimeSeconds)} ·
                  Última lectura: {formatTime(device.capturedAt)}
                </p>
                <InterfaceTable interfaces={device.interfaces} />
              </article>
            ))
          )}
          <div className="snmp-security-check">
            <p className="muted-copy">
              Puedes pedir a la IA que revise los puertos conocidos de los
              equipos privados configurados en <code>SNMP_DEVICES</code> y
              relacione esa exposición con las últimas lecturas SNMP. Solo se
              comprueban puertos TCP; no se buscan versiones ni se explotan
              servicios.
            </p>
            <label className="authorization-check">
              <input
                type="checkbox"
                checked={snmpScanAuthorized}
                onChange={(event) => setSnmpScanAuthorized(event.target.checked)}
                disabled={busy}
              />
              Confirmo que tengo autorización para revisar los puertos de los
              dispositivos configurados.
            </label>
            <button
              className="button button-secondary"
              onClick={handleSnmpExposureAnalysis}
              disabled={busy || !snmpScanAuthorized}
            >
              {busy ? "Analizando…" : "Analizar puertos y riesgos con IA"}
            </button>
          </div>
          {snmpExposureAnalysis && (
            <div className="scan-results" aria-live="polite">
              <h3>Puertos y riesgos por dispositivo</h3>
              {snmpExposureAnalysis.deviceResults.map((item) => (
                <article className="risk-box" key={item.ip}>
                  <h3>{item.name} · {item.ip}</h3>
                  <p className="cell-secondary">
                    Puertos comprobados: {item.exposure.checkedPorts.length}
                  </p>
                  {item.exposure.exposedServices.length === 0 ? (
                    <p>
                      No se detectaron servicios accesibles en los puertos
                      comprobados. Esto no descarta otras vulnerabilidades.
                    </p>
                  ) : (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Servicio</th>
                            <th>Puerto</th>
                            <th>Riesgo preliminar</th>
                            <th>Recomendación</th>
                          </tr>
                        </thead>
                        <tbody>
                          {item.exposure.exposedServices.map((service) => (
                            <tr key={service.port}>
                              <td>{service.service}</td>
                              <td>{service.port}</td>
                              <td>
                                <Badge variant={riskClass[service.severity]}>
                                  {service.severity}
                                </Badge>
                              </td>
                              <td>{service.recommendation}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {!item.snmpObservation && (
                    <p className="cell-secondary">
                      No hay una lectura SNMPv3 guardada para este equipo.
                    </p>
                  )}
                </article>
              ))}
              <h3>Análisis de IA</h3>
              <p className="ollama-analysis">{snmpExposureAnalysis.analysis}</p>
              <p className="chart-summary">
                Los puertos abiertos son indicios de exposición, no
                vulnerabilidades confirmadas. La IA no recibe versiones ni
                información CVE.
              </p>
            </div>
          )}
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
            Fuente única de dispositivos: <code>laptop.csv</code>.
            <br />
            Métricas y alertas: solo se muestran si existen datos guardados.
            <br />
            Persistencia: {dashboard.database}.
            <br />
            SNMPv3 (opcional): solo para equipos que estén incluidos en el CSV.
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

import { FormEvent, useEffect, useState } from "react";
import { downloadFilename, parseCoupangProduct } from "./lib/coupang";

const EXAMPLE_URL =
  "https://www.coupang.com/vp/products/1920045216?itemId=3260034071&vendorItemId=71284447167";

type Phase = "idle" | "validating" | "fetching" | "done" | "error";

type ExportResult = {
  count: number;
  downloadUrl: string;
  filename: string;
  productId: string;
};

const railSteps = ["Product URL", "Review pages", "CSV file"];

function triggerDownload(downloadUrl: string, filename: string) {
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function App() {
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<ExportResult | null>(null);
  const [errorStep, setErrorStep] = useState(0);

  useEffect(() => {
    return () => {
      if (result?.downloadUrl) {
        URL.revokeObjectURL(result.downloadUrl);
      }
    };
  }, [result?.downloadUrl]);

  const isBusy = phase === "validating" || phase === "fetching";
  const activeStep = phase === "idle"
    ? -1
    : phase === "validating"
      ? 0
      : phase === "fetching"
        ? 1
        : phase === "error"
          ? errorStep
          : 2;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setResult(null);
    setErrorStep(0);
    setPhase("validating");

    let product;
    try {
      product = parseCoupangProduct(url);
    } catch (error) {
      setErrorStep(0);
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "Enter a valid Coupang product URL.");
      return;
    }

    const fetchStageTimer = window.setTimeout(() => setPhase("fetching"), 450);
    try {
      const response = await fetch("/api/reviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: product.normalizedUrl, sortBy: "DATE_DESC" }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(body?.message ?? `The exporter returned HTTP ${response.status}.`);
      }

      const blob = await response.blob();
      const downloadUrl = URL.createObjectURL(blob);
      const count = Number(response.headers.get("x-review-count") ?? "0");
      const filename = downloadFilename(response.headers.get("content-disposition"), product.productId);
      const exportResult = { count, downloadUrl, filename, productId: product.productId };

      setResult(exportResult);
      setPhase("done");
      triggerDownload(downloadUrl, filename);
    } catch (error) {
      setErrorStep(1);
      setPhase("error");
      setMessage(error instanceof Error ? error.message : "The export failed. Retry in a moment.");
    } finally {
      window.clearTimeout(fetchStageTimer);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Coupang Review CSV home">
          <span className="wordmark-mark" aria-hidden="true">CSV</span>
          <span>Coupang Review CSV</span>
        </a>
        <span className="runtime-note">Seoul function · no data stored</span>
      </header>

      <main className="workspace">
        <section className="intro" aria-labelledby="page-title">
          <p className="eyebrow">PUBLIC REVIEW EXPORTER</p>
          <h1 id="page-title">One product URL in. Every review out.</h1>
          <p className="lede">
            Paste a Coupang product page. The server walks every review page and returns a UTF-8 CSV,
            ready for Excel, Sheets, or a research notebook.
          </p>
        </section>

        <section className="export-panel" aria-label="Review export form">
          <form onSubmit={handleSubmit} aria-busy={isBusy}>
            <div className="field-heading">
              <label htmlFor="product-url">Coupang product URL</label>
              <button
                className="example-button"
                type="button"
                onClick={() => {
                  setUrl(EXAMPLE_URL);
                  setMessage("");
                  setErrorStep(0);
                  setPhase("idle");
                }}
                disabled={isBusy}
              >
                Load example
              </button>
            </div>

            <div className="input-row">
              <input
                id="product-url"
                name="product-url"
                type="url"
                inputMode="url"
                autoComplete="url"
                placeholder="https://www.coupang.com/vp/products/..."
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                disabled={isBusy}
                required
              />
              <button className="export-button" type="submit" disabled={isBusy || !url.trim()}>
                {isBusy ? "Exporting…" : "Export all reviews"}
                <span aria-hidden="true">↓</span>
              </button>
            </div>

            <p className="field-note">Large products can take 10–45 seconds. Keep this tab open.</p>
          </form>

          <ol className="extraction-rail" aria-label="Export progress">
            {railSteps.map((step, index) => {
              const state = phase === "error" && index === activeStep
                ? "error"
                : index < activeStep || phase === "done"
                  ? "complete"
                  : index === activeStep
                    ? "active"
                    : "waiting";
              return (
                <li className={`rail-step rail-step--${state}`} key={step}>
                  <span className="rail-node" aria-hidden="true" />
                  <span className="rail-label">{step}</span>
                </li>
              );
            })}
          </ol>

          <div className="status-region" aria-live="polite">
            {phase === "fetching" ? (
              <p className="status status--working">
                Paging reviews and removing duplicate review IDs…
              </p>
            ) : null}
            {phase === "error" ? <p className="status status--error">{message}</p> : null}
            {phase === "done" && result ? (
              <div className="receipt">
                <div>
                  <span className="receipt-label">EXPORT COMPLETE</span>
                  <strong>{result.count.toLocaleString()} reviews</strong>
                  <span className="receipt-meta">Product {result.productId} · UTF-8 CSV</span>
                </div>
                <button
                  className="download-again"
                  type="button"
                  onClick={() => triggerDownload(result.downloadUrl, result.filename)}
                >
                  Download again
                </button>
              </div>
            ) : null}
          </div>
        </section>

        <aside className="privacy-note">
          <span className="privacy-index">01</span>
          <p>
            The function streams the finished CSV back to your browser. It does not write review data to
            a database. Use public review data responsibly and follow Coupang’s terms and applicable law.
          </p>
        </aside>
      </main>
    </div>
  );
}

export default App;

import { useCallback, useEffect, useState } from "react";
import {
  analyzeCode,
  fixFixture,
  getFixtures,
  getHealth,
  getRecorded,
} from "./api.js";
import "./App.css";

const EXAMPLE_CODE =
  "def calculate_average(numbers):\n    return sum(numbers) / len(numbers)\n\nprint(calculate_average([]))";
const EXAMPLE_ERROR = "ZeroDivisionError: division by zero";
const MAX_INPUT_SIZE = 100_000;
const readable = (name = "") =>
  name.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const byteLength = (value) => new TextEncoder().encode(value).length;

function StatusBadge({ status }) {
  const knownStatus = ["passed", "failed", "not_run"].includes(status)
    ? status
    : "not_run";
  return (
    <span className={`status-pill ${knownStatus}`}>
      {readable(knownStatus)}
    </span>
  );
}

function OutputPanel({ title, value, tone = "neutral", status }) {
  return (
    <section className={`output-panel ${tone}`}>
      <div className="panel-heading">
        <h3>{title}</h3>
        {status && <StatusBadge status={status} />}
      </div>
      <pre>{value || "No test output was returned."}</pre>
    </section>
  );
}

function FixtureProof() {
  const [fixtures, setFixtures] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [recordedError, setRecordedError] = useState("");
  const fixture = fixtures.find((item) => item.id === selectedId);
  const diagnosis =
    result?.diagnosis && typeof result.diagnosis === "object"
      ? result.diagnosis
      : {};
  const verified = result?.after?.status === "passed";

  useEffect(() => {
    let active = true;
    getFixtures()
      .then((items) => {
        if (!active) return;
        if (!Array.isArray(items))
          throw new Error("The API returned an unexpected fixture list.");
        setFixtures(items);
        setSelectedId(items[0]?.id || "");
      })
      .catch((loadError) => active && setError(loadError.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const runFix = useCallback(async () => {
    if (!fixture) return;
    setBusy(true);
    setError("");
    setRecordedError("");
    setResult(null);
    try {
      setResult(await fixFixture(fixture.id));
    } catch (fixError) {
      setError(fixError.message);
    } finally {
      setBusy(false);
    }
  }, [fixture]);

  async function showRecorded() {
    setBusy(true);
    setRecordedError("");
    try {
      const payload = await getRecorded();
      const saved =
        payload?.result && typeof payload.result === "object"
          ? payload.result
          : payload;
      setResult(
        saved && typeof saved === "object"
          ? { ...saved, __recorded: true }
          : { __recorded: true }
      );
      setError("");
    } catch (recordError) {
      setRecordedError(recordError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="fixture-mode" aria-labelledby="fixture-title">
      <div className="fixture-mode-heading">
        <div>
          <div className="section-kicker">ALSO IN FIXPROOF</div>
          <h2 id="fixture-title">Prove a built-in fixture</h2>
          <p>
            These examples include real failing tests and can be verified end to
            end.
          </p>
        </div>
        <label className="fixture-select-label">
          Fixture
          <select
            value={selectedId}
            onChange={(event) => {
              setSelectedId(event.target.value);
              setResult(null);
              setError("");
            }}
            disabled={loading || !fixtures.length}
          >
            {fixtures.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title || item.id}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loading && <p className="inline-state">Loading fixtures…</p>}
      {error && (
        <div className="notice error-notice" role="alert">
          {error}
        </div>
      )}
      {fixture && (
        <div className="source-grid">
          <section className="code-card">
            <div className="code-card-head">
              <span>
                <i className="dot red-dot" /> BUGGY CODE
              </span>
              <span>Python</span>
            </div>
            <pre>{fixture.code}</pre>
          </section>
          <OutputPanel
            title="REAL FAILING TEST OUTPUT"
            value={fixture.error}
            tone="failure"
            status="failed"
          />
        </div>
      )}
      <div className="action-row">
        <p>Here the backend runs the fixture tests before and after the fix.</p>
        <button
          className="primary-button"
          type="button"
          onClick={runFix}
          disabled={!fixture || busy}
        >
          {busy ? (
            <>
              <span className="spinner" /> Running verification…
            </>
          ) : (
            <>
              Fix &amp; Prove <span aria-hidden="true">↗</span>
            </>
          )}
        </button>
      </div>
      {error && (
        <div className="notice error-notice fixture-error">
          <span>{error}</span>
          <button
            className="secondary-button"
            type="button"
            onClick={showRecorded}
            disabled={busy}
          >
            Show recorded demo
          </button>
          {recordedError && <span>{recordedError}</span>}
        </div>
      )}
      {result && (
        <div className="fixture-result" aria-live="polite">
          <div className="badge-row">
            {result.__recorded && (
              <span className="badge recorded-badge">Recorded result</span>
            )}
            {result.simulated === true || diagnosis.simulated === true ? (
              <span className="badge simulated-badge">Simulated diagnosis</span>
            ) : null}
          </div>
          {!verified && (
            <div className="could-not-verify">
              <strong>Could not verify this fix</strong>
              <span>The tests did not return a passed status.</span>
            </div>
          )}
          <div className="result-panels">
            <OutputPanel
              title="BEFORE"
              value={result.before?.output}
              tone="failure"
              status={result.before?.status || "not_run"}
            />
            <OutputPanel
              title="AFTER"
              value={result.after?.output}
              tone={verified ? "success" : "failure"}
              status={result.after?.status || "not_run"}
            />
          </div>
          {(diagnosis.cause || diagnosis.explanation) && (
            <section className="diagnosis-card">
              <div className="section-kicker">THE DIAGNOSIS</div>
              {diagnosis.cause && <h3>{diagnosis.cause}</h3>}
              {diagnosis.explanation && <p>{diagnosis.explanation}</p>}
            </section>
          )}
          {diagnosis.fixed_code && (
            <section
              className={`code-card fixture-fixed-code ${
                verified ? "verified-code" : "unverified-code"
              }`}
            >
              <div className="code-card-head">
                <span>{verified ? "VERIFIED FIX" : "UNVERIFIED PROPOSAL"}</span>
                <span>Python</span>
              </div>
              <pre>{diagnosis.fixed_code}</pre>
            </section>
          )}
          {Array.isArray(result.report) && (
            <ul className="fixture-report">
              {result.report.map((check, index) => (
                <li key={`${check.name}-${index}`}>
                  <span className={`check-icon ${check.status}`}>
                    {check.status === "passed"
                      ? "✓"
                      : check.status === "failed"
                      ? "×"
                      : "·"}
                  </span>
                  {readable(check.name)}
                  <StatusBadge status={check.status} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function App() {
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState("");
  const [errorText, setErrorText] = useState("");
  const [fileName, setFileName] = useState("");
  const [health, setHealth] = useState({
    state: "checking",
    configured: false,
  });
  const [healthAttempt, setHealthAttempt] = useState(0);
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [requestError, setRequestError] = useState("");
  const [validationError, setValidationError] = useState("");
  const [copyMessage, setCopyMessage] = useState("");

  useEffect(() => {
    let active = true;
    getHealth()
      .then((status) => {
        if (!active) return;
        setHealth(
          status?.ok === true
            ? {
                state: "connected",
                configured: status.ai_configured === true,
                model: status.model || null,
              }
            : { state: "unavailable", configured: false }
        );
      })
      .catch(
        () => active && setHealth({ state: "unavailable", configured: false })
      );
    return () => {
      active = false;
    };
  }, [healthAttempt]);

  async function submitAnalysis(event) {
    event?.preventDefault();
    setValidationError("");
    setRequestError("");
    setCopyMessage("");
    if (!code.trim() || !errorText.trim()) {
      setValidationError(
        "Add both your Python code and the error message to continue."
      );
      return;
    }
    if (
      byteLength(code) > MAX_INPUT_SIZE ||
      byteLength(errorText) > MAX_INPUT_SIZE
    ) {
      setValidationError("Code and error message must each be under 100 KB.");
      return;
    }
    if (language !== "python") {
      setValidationError(
        "Only Python is supported right now. Choose Python to continue."
      );
      return;
    }
    setAnalyzing(true);
    setAnalysis(null);
    try {
      setAnalysis(
        await analyzeCode({ language, code, error_message: errorText })
      );
    } catch (analysisError) {
      setRequestError(analysisError.message);
    } finally {
      setAnalyzing(false);
    }
  }

  function loadExample() {
    setLanguage("python");
    setCode(EXAMPLE_CODE);
    setErrorText(EXAMPLE_ERROR);
    setFileName("");
    setAnalysis(null);
    setRequestError("");
    setValidationError("");
  }

  function clearInput() {
    if (
      (code || errorText) &&
      !window.confirm("Clear the code and error message?")
    )
      return;
    setLanguage("python");
    setCode("");
    setErrorText("");
    setFileName("");
    setAnalysis(null);
    setRequestError("");
    setValidationError("");
    setCopyMessage("");
  }

  function newAnalysis() {
    if (
      (code || errorText) &&
      !window.confirm("Start a new analysis and clear the current input?")
    )
      return;
    setLanguage("python");
    setCode("");
    setErrorText("");
    setFileName("");
    setAnalysis(null);
    setRequestError("");
    setValidationError("");
    setCopyMessage("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function importFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    setValidationError("");
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".py")) {
      setValidationError("Choose a Python source file ending in .py.");
      return;
    }
    if (file.size > MAX_INPUT_SIZE) {
      setValidationError(
        "That file is larger than 100 KB. Choose a smaller Python file."
      );
      return;
    }
    try {
      setCode(await file.text());
      setFileName(file.name);
      setLanguage("python");
      setAnalysis(null);
      setRequestError("");
    } catch {
      setValidationError(
        "The selected file could not be read. Try another .py file."
      );
    }
  }

  async function copyFix() {
    try {
      await navigator.clipboard.writeText(analysis.fixed_code);
      setCopyMessage("Fix copied to clipboard.");
    } catch {
      setCopyMessage(
        "Clipboard access failed. Select and copy the code manually."
      );
    }
  }

  const verificationStatus = analysis?.verification?.status || "not_run";
  const supportedLanguage = language === "python";

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="FixProof home">
          <span className="brand-mark">{"{ }"}</span>
          <span>
            FixProof <small>AI</small>
          </span>
        </a>
        <div className="header-actions">
          <span className={`connection-pill ${health.state}`}>
            <i />
            {health.state === "checking"
              ? "Checking API"
              : health.state === "connected"
              ? "API connected"
              : "API unavailable"}
          </span>
          {health.state === "connected" && !health.configured && (
            <span className="ai-config-note">AI key not configured</span>
          )}
          {health.state === "connected" &&
            health.configured &&
            health.model && <span className="model-note">{health.model}</span>}
          <button
            className="new-analysis-button"
            type="button"
            onClick={newAnalysis}
          >
            ＋ New Analysis
          </button>
        </div>
      </header>

      <main id="top" className="analyzer-main">
        <section className="intro">
          <div className="eyebrow">
            <span className="eyebrow-dot" /> FROM ERROR TO EVIDENCE
          </div>
          <h1>
            Make the error
            <br />
            <em>make sense.</em>
          </h1>
          <p className="intro-subline">
            Paste the code. Share the error. Get a clear next step.
          </p>
        </section>

        <div className="analyzer-layout">
          <section
            className="workbench analyzer-card"
            aria-labelledby="analyzer-title"
          >
            <div className="workbench-top">
              <div>
                <div className="section-kicker">01 / YOUR INPUT</div>
                <h2 id="analyzer-title">Show us what broke</h2>
              </div>
              <span className="language-chip">
                {language === "python" ? "🐍 Python" : language}
              </span>
            </div>
            <form onSubmit={submitAnalysis}>
              <div className="language-import-row">
                <label className="fixture-select-label language-label">
                  Language
                  <select
                    value={language}
                    onChange={(event) => {
                      setLanguage(event.target.value);
                      setValidationError("");
                      setRequestError("");
                      setAnalysis(null);
                    }}
                  >
                    <option value="python">Python</option>
                    <option value="javascript">
                      JavaScript (not supported yet)
                    </option>
                  </select>
                </label>
                <div className="input-actions">
                  <label className="upload-button">
                    ＋ Insert .py file
                    <input
                      type="file"
                      accept=".py,text/x-python,text/plain"
                      onChange={importFile}
                    />
                  </label>
                  <button
                    type="button"
                    className="quiet-button"
                    onClick={loadExample}
                  >
                    Load Example
                  </button>
                  <button
                    type="button"
                    className="quiet-button"
                    onClick={clearInput}
                  >
                    Clear
                  </button>
                </div>
              </div>
              {fileName && (
                <div className="file-loaded">
                  <span>FILE INSERTED</span>
                  <strong>{fileName}</strong>
                  <button
                    type="button"
                    onClick={() => setFileName("")}
                    aria-label="Remove filename label"
                  >
                    ×
                  </button>
                </div>
              )}
              <label className="field-label" htmlFor="source-code">
                Your code <span>required · up to 100 KB</span>
              </label>
              <textarea
                id="source-code"
                className="editor code-editor"
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                  setAnalysis(null);
                  setRequestError("");
                  setValidationError("");
                }}
                placeholder={
                  "def calculate_total(items):\n    return sum(items)"
                }
                spellCheck="false"
                autoCapitalize="off"
                autoComplete="off"
              />
              <label
                className="field-label error-field-label"
                htmlFor="error-message"
              >
                Error message <span>required · up to 100 KB</span>
              </label>
              <textarea
                id="error-message"
                className="editor error-editor"
                value={errorText}
                onChange={(event) => {
                  setErrorText(event.target.value);
                  setAnalysis(null);
                  setRequestError("");
                  setValidationError("");
                }}
                placeholder="Paste the traceback or error message here…"
                spellCheck="false"
              />
              {validationError && (
                <div className="inline-validation" role="alert">
                  {validationError}
                </div>
              )}
              {requestError && (
                <div className="request-error" role="alert">
                  <div>
                    <strong>Analysis didn’t go through.</strong>
                    <span>{requestError}</span>
                  </div>
                  <button
                    type="button"
                    className="retry-button"
                    onClick={submitAnalysis}
                    disabled={analyzing}
                  >
                    Retry
                  </button>
                </div>
              )}
              <div className="analyze-footer">
                <span>Your code is sent to the backend for diagnosis.</span>
                <button
                  className="primary-button analyze-button"
                  type="submit"
                  disabled={analyzing}
                >
                  {analyzing ? (
                    <>
                      <span className="spinner" /> Analyzing code and error…
                    </>
                  ) : (
                    <>
                      Analyze Error <span aria-hidden="true">↗</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </section>

          <section
            className={`analysis-panel ${analysis ? "has-analysis" : ""}`}
            aria-live="polite"
          >
            <div className="analysis-panel-head">
              <div>
                <div className="section-kicker">02 / THE DIAGNOSIS</div>
                <h2>Understand the failure</h2>
              </div>
              {analysis?.simulated && (
                <span className="badge simulated-badge">
                  Simulated diagnosis
                </span>
              )}
            </div>
            {analyzing ? (
              <div className="analysis-empty loading-state">
                <span className="large-spinner" />
                <h3>Analyzing code and error…</h3>
                <p>Waiting for the backend diagnosis.</p>
              </div>
            ) : !analysis ? (
              <div className="analysis-empty">
                <div className="empty-icon">⌁</div>
                <h3>Your next fix starts with understanding the error.</h3>
                <p>
                  Submit code and its error message to see a diagnosis here.
                </p>
                <div className="empty-rule">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : (
              <div className="analysis-content">
                <article className="result-section root-cause">
                  <div className="result-label">
                    <span className="result-icon">!</span> ROOT CAUSE
                  </div>
                  <h3>{analysis.root_cause}</h3>
                </article>
                <article className="result-section">
                  <div className="result-label">DETAILED EXPLANATION</div>
                  <p>{analysis.explanation}</p>
                </article>
                <article className="result-section proposed-fix">
                  <div className="result-heading">
                    <div className="result-label">PROPOSED FIX</div>
                    <button
                      type="button"
                      className="copy-button"
                      onClick={copyFix}
                    >
                      ▣ Copy Fix
                    </button>
                  </div>
                  <pre className="fixed-code">{analysis.fixed_code}</pre>
                  {copyMessage && (
                    <span className="copy-message" role="status">
                      {copyMessage}
                    </span>
                  )}
                </article>
                <article className="result-section">
                  <div className="result-label">WHAT CHANGED</div>
                  {analysis.changes.length ? (
                    <ul className="result-list">
                      {analysis.changes.map((change, index) => (
                        <li key={index}>{change}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty-result-note">
                      The diagnosis API did not return a change list.
                    </p>
                  )}
                </article>
                <article className="result-section">
                  <div className="result-label">SUGGESTED TESTS</div>
                  {analysis.suggested_tests.length ? (
                    <ul className="suggested-tests">
                      {analysis.suggested_tests.map((test, index) => (
                        <li key={`${test.name}-${index}`}>
                          <strong>{test.name}</strong>
                          <span>{test.description}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty-result-note">
                      No test suggestions were returned.
                    </p>
                  )}
                </article>
                <article className="verification-evidence">
                  <div className="result-label">VERIFICATION EVIDENCE</div>
                  <div className="verification-row">
                    <StatusBadge status={verificationStatus} />
                    <p>{analysis.verification.message}</p>
                  </div>
                  <p className="verification-honesty">
                    A diagnosis is not a test run. No pass is claimed here.
                  </p>
                </article>
              </div>
            )}
          </section>
        </div>

        <FixtureProof />
      </main>
      <footer>
        FixProof AI · From Error to Evidence. Diagnosis is not proof until tests
        run.
      </footer>
    </div>
  );
}

export default App;

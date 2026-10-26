const TOKEN = document.querySelector('meta[name="estatement-token"]').content;
const api = (path, opts = {}) =>
  fetch(path, { ...opts, headers: { ...opts.headers, "X-Token": TOKEN } }).then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r;
  });
const fmt = (n) =>
  Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

document.addEventListener("alpine:init", () =>
  Alpine.data("app", () => ({
    accounts: [],
    statements: [],
    rows: [],
    results: [],
    f: { account: "", start: "", end: "", q: "" },
    backend: "auto",
    allow: false,
    over: false,
    loaded: false,
    ocr: null,
    ocrPrompt: false,
    job: null,

    init() {
      this.refresh();
      this.checkOcr();
      this.resumeImport();
      this.$watch("backend", (b) => {
        if (b === "vlm") this.ocrPrompt = true;
      });
    },
    fmt,

    params() {
      const p = new URLSearchParams();
      if (this.f.account) p.set("account", this.f.account);
      if (this.f.start) p.set("start", this.f.start + "-01");
      if (this.f.end) p.set("end", this.f.end + "-31");
      if (this.f.q) p.set("q", this.f.q);
      return p;
    },
    get totals() {
      let tin = 0,
        tout = 0;
      for (const r of this.rows) {
        const a = Number(r.amount);
        if (a > 0) tin += a;
        else tout += a;
      }
      return { tin, tout, net: tin + tout };
    },

    get showOcr() {
      return this.ocr?.available && !this.ocr.installed && (this.ocrPrompt || this.ocr.downloading);
    },
    get ocrProgress() {
      const { done_bytes, total_bytes } = this.ocr;
      return `${(done_bytes / 1e9).toFixed(2)} of ${(total_bytes / 1e9).toFixed(1)} GB`;
    },
    async checkOcr() {
      this.ocr = await (await api("/api/ocr-model")).json();
      if (this.ocr.downloading) setTimeout(() => this.checkOcr(), 1000);
    },
    async downloadOcr() {
      this.ocr = await (await api("/api/ocr-model/download", { method: "POST" })).json();
      if (this.ocr.downloading) setTimeout(() => this.checkOcr(), 1000);
    },

    // Fraction done for the import bar, or null while unknown (indeterminate bar).
    get jobFraction() {
      const j = this.job;
      if (!j?.file_count || (j.file_count === 1 && !j.page_count)) return null;
      const within = j.page_count ? (j.page - 1) / j.page_count : 0;
      return (j.file_index - 1 + within) / j.file_count;
    },
    get jobLabel() {
      const j = this.job;
      const parts = [];
      if (j.file_count > 1) parts.push(`File ${j.file_index} of ${j.file_count}`);
      if (j.backend === "vlm") {
        parts.push(j.page_count ? `OCR page ${j.page} of ${j.page_count}` : "Starting OCR");
        if (j.attempt > 1) parts.push(`retry ${j.attempt - 1} at a new resolution`);
      } else {
        parts.push("Reading");
      }
      return parts.join(" · ") + "…";
    },

    async loadTransactions() {
      this.rows = await (await api("/api/transactions?" + this.params())).json();
      this.loaded = true;
    },
    async refresh() {
      const [a, s] = await Promise.all([api("/api/accounts"), api("/api/statements")]);
      this.accounts = await a.json();
      this.statements = await s.json();
      await this.loadTransactions();
    },

    async upload(files) {
      files = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
      if (!files.length) return;
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      fd.append("backend", this.backend);
      fd.append("allow_unreconciled", this.allow);
      this.results = [];
      try {
        this.job = await (await api("/api/import", { method: "POST", body: fd })).json();
      } catch (e) {
        this.results = [{ cls: "bad", file: null, detail: `Import failed: ${e.message}` }];
        return;
      }
      await this.pollImport();
    },
    // After a reload, keep showing an import that is still running.
    async resumeImport() {
      const job = await (await api("/api/import")).json();
      if (!job.running) return;
      this.job = job;
      await this.pollImport();
    },
    async pollImport() {
      try {
        while (this.job.running) {
          await new Promise((r) => setTimeout(r, 500));
          this.job = await (await api("/api/import")).json();
        }
        const res = this.job.results;
        if (res.some((r) => r.needs_ocr_model)) {
          this.ocrPrompt = true;
          await this.checkOcr();
        }
        this.results = res.map((r) => ({
          file: r.file,
          cls: r.status === "imported" ? "ok" : r.status === "duplicate" ? "dup" : "bad",
          detail:
            r.status === "imported"
              ? `${r.bank} ${r.statement_date}: ${r.inserted} rows${r.reconciled ? "" : " (totals differ)"}`
              : r.status === "duplicate"
                ? "already imported"
                : r.status === "rejected"
                  ? `${r.bank} ${r.statement_date}: totals don't match (${r.failed_checks.join(", ")}), not saved`
                  : r.needs_ocr_model
                    ? `${r.error} Download it above, then drop the file again.`
                    : r.error,
        }));
      } catch (e) {
        this.results = [{ cls: "bad", file: null, detail: `Import failed: ${e.message}` }];
      }
      this.job = null;
      this.refresh();
    },

    async remove(id) {
      if (!confirm("Remove this statement and its transactions from the database?")) return;
      await api(`/api/statements/${id}`, { method: "DELETE" });
      this.refresh();
    },

    async exportCsv() {
      const res = await api("/api/export.csv?" + this.params());
      if (window.pywebview?.api) {
        await window.pywebview.api.save_csv(await res.text());
        return;
      }
      const blob = await res.blob();
      const a = Object.assign(document.createElement("a"), {
        href: URL.createObjectURL(blob),
        download: "transactions.csv",
      });
      a.click();
      URL.revokeObjectURL(a.href);
    },
  })),
);

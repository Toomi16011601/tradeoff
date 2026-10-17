/* Progressive enhancement: the full report and tables remain readable without JS. */
(() => {
  "use strict";
  const source = document.getElementById("report-data");
  if (!source) return;
  let report;
  try { report = JSON.parse(source.textContent); } catch (_) { return; }
  if (!report.schema_version) return;
  const views = Array.from(document.querySelectorAll("main > section.view"));
  const links = Array.from(document.querySelectorAll(".view-nav a[data-view]"));
  const ids = views.map(view => view.id);
  function activateView(scroll) {
    const requested = location.hash.slice(1);
    const selected = ids.includes(requested) ? requested : "overview";
    views.forEach(view => { view.hidden = view.id !== selected; });
    links.forEach(link => {
      if (link.dataset.view === selected) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (scroll) window.scrollTo(0, 0);
  }
  document.documentElement.classList.add("enhanced");
  activateView(false);
  window.addEventListener("hashchange", () => activateView(true));
  links.forEach((link, index) => link.addEventListener("keydown", event => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % links.length;
    else if (event.key === "ArrowLeft") next = (index + links.length - 1) % links.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = links.length - 1;
    else return;
    event.preventDefault();
    links[next].focus();
    location.hash = links[next].dataset.view;
  }));
  const economics = report.economics || {};
  const original = (economics.original || {}).equity_curve || [];
  const intervention = (economics.intervention || {}).equity_curve || [];
  const baseline = (report.baseline || {}).trace || [];
  const mutated = (report.witness || {}).mutated_trace || [];
  const slider = document.getElementById("inspection-cursor");
  const chart = document.getElementById("equity-chart");
  const prev = document.getElementById("cursor-prev");
  const next = document.getElementById("cursor-next");
  const numeric = value => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "—";
  const setText = (id, text) => { const node = document.getElementById(id); if (node) node.textContent = text; };
  const pairByTime = new Map(intervention.map(point => [point.timestamp, point]));
  const displayTargets = report.display_targets || {};
  const targetsByTime = new Map(baseline.map((point, index) => [point.timestamp, (displayTargets.original || [])[index] ?? point.target]));
  const pairedTargetsByTime = new Map(mutated.map((point, index) => [point.timestamp, (displayTargets.intervention || [])[index] ?? point.target]));
  function inspect(value) {
    if (!slider || !original.length) return;
    const index = Math.max(0, Math.min(original.length - 1, Number(value)));
    const point = original[index];
    const paired = pairByTime.get(point.timestamp);
    slider.value = String(index);
    slider.setAttribute("aria-valuetext", `Bar ${index + 1}: ${point.timestamp}`);
    setText("cursor-counter", `${String(index + 1).padStart(2, "0")} / ${String(original.length).padStart(2, "0")}`);
    setText("cursor-timestamp", point.timestamp);
    setText("cursor-original-value", numeric(point.equity));
    setText("cursor-intervention-value", numeric(paired && paired.equity));
    setText("cursor-original-target", targetsByTime.get(point.timestamp) ?? "—");
    setText("cursor-intervention-target", pairedTargetsByTime.get(point.timestamp) ?? "—");
    if (prev) prev.disabled = index === 0;
    if (next) next.disabled = index === original.length - 1;
    const table = document.getElementById("equity-table");
    if (table) Array.from(table.tBodies[0].rows).forEach((row, rowIndex) => {
      if (rowIndex === index) row.setAttribute("aria-current", "true");
      else row.removeAttribute("aria-current");
    });
    if (chart) {
      const left = Number(chart.dataset.left);
      const top = Number(chart.dataset.top);
      const width = Number(chart.dataset.width);
      const height = Number(chart.dataset.height);
      const low = Number(chart.dataset.lo);
      const high = Number(chart.dataset.hi);
      const x = left + width * index / Math.max(original.length - 1, 1);
      const y = equity => top + height * (high - equity) / (high - low);
      const line = document.getElementById("cursor-line");
      const dot = document.getElementById("cursor-original");
      const pairedDot = document.getElementById("cursor-intervention");
      line.setAttribute("x1", String(x));
      line.setAttribute("x2", String(x));
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(y(point.equity)));
      if (pairedDot && paired) {
        pairedDot.setAttribute("cx", String(x));
        pairedDot.setAttribute("cy", String(y(paired.equity)));
      }
    }
  }
  if (slider) {
    slider.addEventListener("input", () => inspect(slider.value));
    if (prev) prev.addEventListener("click", () => inspect(Number(slider.value) - 1));
    if (next) next.addEventListener("click", () => inspect(Number(slider.value) + 1));
    if (chart) chart.addEventListener("click", event => {
      const bounds = chart.getBoundingClientRect();
      const x = (event.clientX - bounds.left) * chart.viewBox.baseVal.width / bounds.width;
      const index = Math.round((x - Number(chart.dataset.left)) / Number(chart.dataset.width) * (original.length - 1));
      inspect(index);
    });
    inspect(slider.value);
  }
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copy);
    if (!target) return;
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(target.textContent);
      setText("copy-status", "Command copied. Run it from the export directory.");
    } catch (_) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      selection.removeAllRanges();
      selection.addRange(range);
      setText("copy-status", "Command selected. Use your keyboard or context menu to copy.");
    }
  }));
})();

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
  let stopRecordedPlayback = () => {};
  function activateView(scroll) {
    stopRecordedPlayback();
    const requested = location.hash.slice(1);
    const selected = ids.includes(requested) ? requested : "overview";
    views.forEach(view => { view.hidden = view.id !== selected; });
    links.forEach(link => {
      if (link.dataset.view === selected) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    const fixture = requested === "saved-fixture" ? document.getElementById("saved-fixture") : null;
    if (fixture) {
      fixture.open = true;
      fixture.scrollIntoView({block: "start"});
      const summary = fixture.querySelector("summary");
      if (summary) summary.focus({preventScroll: true});
    } else if (scroll) window.scrollTo(0, 0);
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
    // Native fragment navigation resets focus after this key handler in Chrome.
    // Keep each view in history without triggering that fragment focus step.
    const fragment = "#" + links[next].dataset.view;
    if (location.hash !== fragment) history.pushState(null, "", fragment);
    activateView(true);
    links[next].focus();
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
  // Recorded evidence is independent of the optional economic projection.
  const workstation = report.workstation || {};
  const bars = workstation.bars || [];
  const traceSlider = document.getElementById("trace-scrubber");
  const traceChart = document.getElementById("temporal-chart");
  const tracePlay = document.getElementById("trace-replay");
  const tracePrevious = document.getElementById("trace-previous");
  const traceNext = document.getElementById("trace-next");
  const traceRange = document.getElementById("trace-range");
  let traceTimer = null;
  let viewStart = workstation.focus_start || 0;
  let viewEnd = workstation.focus_end ?? Math.max(bars.length - 1, 0);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const plotNumber = value => value !== null && value !== undefined && Number.isFinite(Number(value));
  const exactText = value => value === null || value === undefined ? "—" : String(value);
  const rangeBounds = values => {
    let low = Infinity, high = -Infinity;
    for (const value of values) {
      if (value < low) low = value;
      if (value > high) high = value;
    }
    const pad = Math.max((high - low) * .09, Math.max(Math.abs(low), Math.abs(high), 1) * .0005);
    const lower = Number.isFinite(low-pad) ? low-pad : low;
    const upper = Number.isFinite(high+pad) ? high+pad : high;
    if (!Number.isFinite(upper-lower)) return [low,high];
    return lower === upper ? [low*(1-Number.EPSILON),high] : [lower,upper];
  };
  const shortUtc = stamp => {
    const value = new Date(stamp);
    return stamp && Number.isFinite(value.getTime()) ? value.toLocaleString("en-US", {month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23",timeZone:"UTC"}).replace(",", " ·") + " UTC" : "Not recorded";
  };
  const priceText = value => finite(Number(value)) ? (Math.abs(Number(value)) >= 10000000 ? Number(value).toPrecision(4) : Number(value).toLocaleString("en-US", {maximumFractionDigits:4})) : "—";
  const axisLabel = value => Math.abs(value) < 100000 ? value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : value.toPrecision(3);
  const svgNode = (tag, attrs, label) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, String(value)));
    if (label !== undefined) node.textContent = label;
    return node;
  };
  function stopTrace() {
    if (traceTimer !== null) clearInterval(traceTimer);
    traceTimer = null;
    if (tracePlay) {
      tracePlay.textContent = "Play trace";
      tracePlay.setAttribute("aria-pressed", "false");
    }
  }
  stopRecordedPlayback = stopTrace;
  function drawTrace() {
    if (!traceChart || !bars.length) return;
    const group = document.getElementById("trace-plot");
    if (!group) return;
    group.replaceChildren();
    const left = 68, width = 812, span = Math.max(viewEnd - viewStart, 1);
    const timeStart = bars[viewStart].time_ms, timeEnd = bars[viewEnd].time_ms;
    const timeSpan = Math.max(timeEnd-timeStart,1);
    const timeX = instant => left + (instant-timeStart)/timeSpan*width;
    const x = index => timeX(bars[index].time_ms);
    const append = (tag, attrs, label) => group.appendChild(svgNode(tag, attrs, label));
    traceChart.dataset.start = String(viewStart);
    traceChart.dataset.end = String(viewEnd);
    for (const [top, bottom] of [[45, 290], [340, 420]]) {
      for (let n = 0; n < 4; n++) {
        const y = top + (bottom - top) * n / 3;
        append("line", {x1:left, x2:880, y1:y, y2:y, class:"chart-grid"});
      }
    }
    const cutoff = workstation.cutoff_index;
    for (let index = viewStart; index <= viewEnd; index++) {
      if (bars[index].unavailable !== true) continue;
      const start = index === viewStart ? left : (x(index-1)+x(index))/2;
      const end = index === viewEnd ? 880 : (x(index)+x(index+1))/2;
      append("rect", {x:start,y:35,width:end-start,height:395,class:"unavailable-region"});
    }
    if (bars.slice(viewStart,viewEnd+1).some(bar=>bar.unavailable === true)) append("text", {x:874,y:32,"text-anchor":"end",class:"chart-label"}, "Shaded input: unavailable at cutoff");
    append("text", {x:left, y:23, class:"chart-track-title"}, "Original OHLC");
    const visible = bars.slice(viewStart, viewEnd + 1);
    const prices = workstation.price_exact_scale ? visible.flatMap(bar => bar.ohlc ? [bar.ohlc.low, bar.ohlc.high] : []).filter(finite) : [];
    if (prices.length) {
      const [low, high] = rangeBounds(prices);
      const y = value => 45 + 245 * ((high - value) / (high - low));
      for (let n = 0; n < 4; n++) {
        append("text", {x:58, y:49 + 245*n/3, "text-anchor":"end", class:"chart-label"}, axisLabel(high-(high-low)*(n/3)));
      }
      const candleWidth = Math.min(8, width / visible.length * .62);
      visible.forEach((bar, offset) => {
        const price = bar.ohlc;
        if (!price || ![price.open, price.high, price.low, price.close].every(finite)) return;
        const cx = x(viewStart + offset), tone = price.close >= price.open ? "candle-up" : "candle-down";
        append("line", {x1:cx, x2:cx, y1:y(price.high), y2:y(price.low), class:`candle-wick ${tone}`});
        append("rect", {x:cx-candleWidth/2, y:Math.min(y(price.open),y(price.close)), width:candleWidth, height:Math.max(.8,Math.abs(y(price.open)-y(price.close))), class:`candle-body ${tone}`});
      });
    } else {
      append("text", {x:left, y:170, class:"chart-empty-label"}, workstation.has_prices ? "Recorded OHLC scale unavailable · exact values in table" : "Recorded OHLC unavailable");
    }
    append("text", {x:left, y:322, class:"chart-track-title"}, `${workstation.units || "Target units"} · step`);
    const targets = visible.flatMap(bar => [bar.original_target,bar.intervention_target]).filter(plotNumber).map(Number);
    if (targets.length && workstation.exact_scale) {
      const [low, high] = rangeBounds(targets);
      const y = value => 340 + 80 * ((high - Number(value)) / (high - low));
      for (let n = 0; n < 3; n++) append("text", {x:58,y:344+40*n,"text-anchor":"end",class:"chart-label"}, axisLabel(high-(high-low)*(n/2)));
      for (const [key, className] of [["original_target","position-original"],["intervention_target","position-intervention"]]) {
        let running = false;
        const path = [];
        visible.forEach((bar, offset) => {
          if (!plotNumber(bar[key])) { running = false; return; }
          const cx = x(viewStart + offset), cy = y(bar[key]);
          path.push(running ? `H${cx}V${cy}` : `M${cx},${cy}`);
          running = true;
        });
        if (path.length) append("path", {d:path.join(" "),class:className});
      }
    } else if (targets.length) {
      append("text", {x:left,y:380,class:"chart-empty-label"}, "Exact values in inspector · scale unavailable");
    }
    const markers = [[workstation.decision_index,"Decision","decision-marker",58],...(workstation.changed_indices || []).map(index => [index,`Changed row ${bars[index].row_index}`,"changed-marker",106])];
    markers.forEach(([index,label,className,labelY]) => {
      if (index === null || index === undefined || index < viewStart || index > viewEnd) return;
      const cx = x(index);
      append("line", {x1:cx,x2:cx,y1:35,y2:430,class:className});
      append("text", {x:Math.min(cx+6,775),y:labelY,class:`${className} marker-label`}, label);
    });
    if (finite(workstation.cutoff_ms) && workstation.cutoff_ms >= timeStart && workstation.cutoff_ms <= timeEnd) {
      const cx = timeX(workstation.cutoff_ms);
      append("line", {x1:cx,x2:cx,y1:35,y2:430,class:"cutoff-marker"});
      append("text", {x:Math.min(cx+6,775),y:82,class:"cutoff-marker marker-label"}, "Cutoff");
    }
    [...new Set([viewStart,viewStart+Math.floor(span/2),viewEnd])].forEach(index => {
      const stamp = bars[index].timestamp;
      append("text", {x:x(index),y:452,"text-anchor":index===viewStart?"start":index===viewEnd?"end":"middle",class:"chart-label"}, `${stamp.slice(5,10)} ${stamp.slice(11,16)}`);
    });
    append("line", {id:"trace-selection",x1:x(Number(traceSlider.value)),x2:x(Number(traceSlider.value)),y1:35,y2:430,class:"trace-selection"});
  }
  function inspectTrace(value, manual = true) {
    if (!traceSlider || !bars.length || !Number.isFinite(Number(value))) return;
    if (manual) stopTrace();
    const index = Math.max(0, Math.min(bars.length - 1, Math.round(Number(value))));
    const bar = bars[index];
    traceSlider.value = String(index);
    traceSlider.setAttribute("aria-valuetext", `Bar ${index}: ${bar.timestamp}`);
    setText("trace-cursor", `Bar ${index} / ${bars.length-1} · ${shortUtc(bar.timestamp)}`);
    setText("selected-original", exactText(bar.original_target));
    setText("selected-intervention", exactText(bar.intervention_target));
    for (const [identity,stamp] of [["selected-timestamp",bar.timestamp],["selected-cutoff",workstation.cutoff],["selected-available",bar.available_at]]) {
      setText(identity, shortUtc(stamp));
      const node = document.getElementById(identity);
      if (node) node.setAttribute("title", exactText(stamp));
    }
    setText("selected-availability", bar.unavailable === true ? "Unavailable" : bar.unavailable === false ? "Available" : "Not recorded");
    setText("selected-row", bar.changed ? exactText(bar.row_index) : "—");
    const ohlc = document.getElementById("selected-ohlc");
    if (ohlc) {
      ohlc.replaceChildren();
      if (!bar.ohlc) ohlc.textContent = "Not recorded";
      else [["open","O"],["high","H"],["low","L"],["close","C"]].forEach(([key,label]) => {
        const cell = document.createElement("span"), name = document.createElement("small"), value = document.createElement("strong");
        cell.setAttribute("class", "ohlc-item");
        name.textContent = label; value.textContent = priceText(bar.ohlc[key]);
        value.setAttribute("title", exactText((bar.ohlc_display || {})[key]));
        cell.appendChild(name); cell.appendChild(value); ohlc.appendChild(cell);
      });
    }
    const changes = document.getElementById("bar-change-details");
    if (changes) {
      changes.replaceChildren();
      if (!(bar.changes || []).length) {
        const empty = document.createElement("p");
        empty.textContent = "No changed fields at this bar.";
        changes.appendChild(empty);
      }
      (bar.changes || []).forEach(change => {
        const row = document.createElement("div"), label = document.createElement("span"), values = document.createElement("strong");
        label.textContent = change.field;
        values.textContent = `${exactText(change.before)} → ${exactText(change.after)}`;
        row.appendChild(label); row.appendChild(values); changes.appendChild(row);
      });
    }
    if (tracePrevious) tracePrevious.disabled = index === 0;
    if (traceNext) traceNext.disabled = index === bars.length - 1;
    if (index < viewStart || index > viewEnd) {
      viewStart = 0; viewEnd = bars.length - 1;
      if (traceRange) traceRange.value = "full";
      drawTrace();
    }
    const cursor = document.getElementById("trace-selection");
    if (cursor) {
      const cx = 68 + (bars[index].time_ms-bars[viewStart].time_ms)/Math.max(bars[viewEnd].time_ms-bars[viewStart].time_ms,1)*812;
      cursor.setAttribute("x1", String(cx)); cursor.setAttribute("x2", String(cx));
      const scroller = document.getElementById("trace-plot-scroll");
      if (scroller && traceChart && (manual || traceTimer !== null) && scroller.scrollWidth > scroller.clientWidth) {
        const chartBounds = traceChart.getBoundingClientRect();
        const viewport = scroller.getBoundingClientRect();
        const position = chartBounds.left - viewport.left + scroller.scrollLeft + cx/900*chartBounds.width;
        let destination = scroller.scrollLeft;
        if (position < scroller.scrollLeft+28) destination = position-scroller.clientWidth*.25;
        else if (position > scroller.scrollLeft+scroller.clientWidth-28) destination = position-scroller.clientWidth*.75;
        scroller.scrollLeft = Math.max(0, Math.min(scroller.scrollWidth-scroller.clientWidth, destination));
      }
    }
  }
  if (traceSlider && bars.length) {
    traceSlider.addEventListener("input", () => inspectTrace(traceSlider.value));
    if (tracePrevious) tracePrevious.addEventListener("click", () => inspectTrace(Number(traceSlider.value)-1));
    if (traceNext) traceNext.addEventListener("click", () => inspectTrace(Number(traceSlider.value)+1));
    if (tracePlay) tracePlay.addEventListener("click", () => {
      if (traceTimer !== null) { stopTrace(); return; }
      if (Number(traceSlider.value) >= bars.length-1) inspectTrace(0);
      tracePlay.textContent = "Pause trace";
      tracePlay.setAttribute("aria-pressed", "true");
      traceTimer = setInterval(() => {
        const index = Number(traceSlider.value)+1;
        inspectTrace(index, false);
        if (index >= bars.length-1) stopTrace();
      }, 650);
    });
    const witnessButton = document.getElementById("witness-select");
    if (witnessButton) witnessButton.addEventListener("click", () => {
      if (workstation.decision_index === null || workstation.decision_index === undefined) return;
      viewStart = workstation.focus_start; viewEnd = workstation.focus_end;
      if (traceRange) traceRange.value = "witness";
      drawTrace(); inspectTrace(workstation.decision_index);
    });
    const changedButton = document.getElementById("changed-row-select");
    if (changedButton) changedButton.addEventListener("click", () => {
      const changed = workstation.changed_indices || [];
      if (!changed.length) return;
      const current = changed.indexOf(Number(traceSlider.value));
      inspectTrace(changed[(current+1)%changed.length]);
    });
    if (traceRange) traceRange.addEventListener("change", () => {
      stopTrace();
      viewStart = traceRange.value === "full" ? 0 : workstation.focus_start;
      viewEnd = traceRange.value === "full" ? bars.length-1 : workstation.focus_end;
      if (Number(traceSlider.value) < viewStart || Number(traceSlider.value) > viewEnd) traceSlider.value = String(workstation.initial_index || 0);
      drawTrace(); inspectTrace(traceSlider.value);
    });
    if (traceChart) traceChart.addEventListener("click", event => {
      const bounds = traceChart.getBoundingClientRect();
      if (!bounds.width) return;
      const x = (event.clientX-bounds.left)*900/bounds.width;
      const instant = bars[viewStart].time_ms+(x-68)/812*(bars[viewEnd].time_ms-bars[viewStart].time_ms);
      let closest = viewStart;
      for (let index=viewStart+1;index<=viewEnd;index++) if (Math.abs(bars[index].time_ms-instant)<Math.abs(bars[closest].time_ms-instant)) closest=index;
      inspectTrace(closest);
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopTrace(); });
    inspectTrace(traceSlider.value);
  }
  const repairSummary = document.querySelectorAll("a.summary-repair");
  repairSummary.forEach(link => link.addEventListener("click", event => {
    event.preventDefault();
    if (location.hash !== "#saved-fixture") history.pushState(null, "", "#saved-fixture");
    activateView(true);
  }));
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copy);
    if (!target) return;
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(target.textContent);
      setText(button.dataset.copyStatus || "copy-status", "Command copied. Use the working directory shown above.");
    } catch (_) {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      selection.removeAllRanges();
      selection.addRange(range);
      setText(button.dataset.copyStatus || "copy-status", "Command selected. Use your keyboard or context menu to copy, then use the working directory shown above.");
    }
  }));
})();

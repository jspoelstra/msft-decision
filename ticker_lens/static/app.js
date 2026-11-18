"use strict";
const form = document.querySelector("#search");
const button = document.querySelector("#submit");
const statusBox = document.querySelector("#status");
const results = document.querySelector("#results");
const tbody = document.querySelector("#articles");
const labels = ["Bullish", "Bearish", "Neutral or mixed", "Unscored"];
const slug = (text) => text.toLowerCase().replaceAll(" ", "-");
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const percent = (value) => `${(value * 100).toFixed(1)}%`;
const weight = (value) => value > 0 && value < 0.005 ? "<0.01" : value.toFixed(2);

function renderLean(data) {
  const {label, score, bearish_weight, bullish_weight} = data.lean;
  document.querySelector("#lean-label").textContent =
    score === null ? label : `${label} (${score > 0 ? "+" : ""}${score})`;
  document.querySelector("#lean-coverage").textContent =
    `${data.tally.Bullish + data.tally.Bearish} directional stories; neutral stories excluded`;
  document.querySelector("#lean-scale").hidden = score === null;
  document.querySelector("#lean-marker").style.left = `${(score + 100) / 2}%`;
  document.querySelector("#bearish-weight").textContent = weight(bearish_weight);
  document.querySelector("#bullish-weight").textContent = weight(bullish_weight);
}

function inspect(row, questions) {
  const details = node("details");
  details.append(node("summary", "Inspect decision API"));
  const panel = node("div", undefined, "inspection");
  panel.append(node("h4", "Input supplied to Foundry"));
  panel.append(node("p", JSON.stringify(row.state, null, 2)));
  if (row.error) panel.append(node("p", row.error));
  for (const [name, question] of Object.entries(questions)) {
    panel.append(node("h4", name.toUpperCase()));
    panel.append(node("p", question.instructions));
    const answer = row.decisions?.answers[name];
    for (const [label, criterion] of Object.entries(question.criteria)) {
      const option = node("div", undefined, "option");
      const description = node("span", `${label}: ${criterion}`);
      option.append(description, node("strong", answer ? percent(answer.probabilities[label]) : "Not scored"));
      panel.append(option);
    }
  }
  if (row.decisions) panel.append(node("p", `Model: ${row.decisions.model}`));
  details.append(panel);
  return details;
}

function render(data) {
  document.querySelector("#result-ticker").textContent = data.ticker;
  document.querySelector("#window").textContent = `${data.start} to ${data.end} UTC`;
  const tallies = document.querySelector("#tallies");
  tallies.replaceChildren();
  for (const label of labels) {
    const tile = node("div", undefined, `tally ${slug(label)}`);
    tile.append(node("strong", String(data.tally[label])), node("span", label));
    tallies.append(tile);
  }
  renderLean(data);
  tbody.replaceChildren();
  for (const row of data.rows) {
    const tr = node("tr");
    const story = node("td");
    const a = node("a", row.article.headline, "headline");
    a.href = row.article.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    story.append(a, node("p", `${row.article.source} / ${new Date(row.article.datetime * 1000).toLocaleString()} / ${row.input_depth}`, "meta"));
    story.append(inspect(row, data.questions));
    tr.append(story);
    for (const name of ["outlook", "impact", "evidence"]) {
      const td = node("td");
      const answer = row.decisions?.answers[name];
      const label = name === "outlook" ? row.bucket : (answer?.choice ?? "Unscored");
      td.append(node("span", label, `badge ${slug(label)}`));
      if (answer) td.append(node("span", `${percent(answer.probabilities[answer.choice])} selected option`, "probability"));
      tr.append(td);
    }
    tbody.append(tr);
  }
  results.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  results.hidden = true;
  statusBox.className = "";
  statusBox.textContent = "Scanning newest-first for 10 bullish or bearish stories through Azure Foundry...";
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ticker: document.querySelector("#ticker").value}),
    });
    if (response.redirected) throw new Error("Your session expired. Reload the page to sign in, then retry.");
    if (response.status === 401 || response.status === 403) throw new Error("Sign in with an authorized account, then retry.");
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Invalid request. Enter a U.S. ticker.");
    render(data);
    const failures = data.tally.Unscored;
    const matches = data.tally.Bullish + data.tally.Bearish;
    statusBox.textContent =
      `${matches} bullish or bearish stories found. Fetched ${data.days_fetched} of up to ${data.lookback_days} days. Checked ${data.scanned} of ${data.available} retrieved unique stories; skipped ${data.neutral_skipped} neutral or mixed.${failures ? ` ${failures} could not be scored; expand those rows for the error.` : ""}${data.scan_error ? ` News retrieval stopped: ${data.scan_error} Results are partial.` : data.scan_timed_out ? " Time limit reached; results are partial. Some requests may have been canceled." : matches < 10 ? ` Reached the end of the ${data.lookback_days}-day news window.` : ""}`;
  } catch (error) {
    statusBox.className = "error";
    statusBox.textContent = error instanceof Error ? error.message : "The request failed.";
  } finally {
    button.disabled = false;
  }
});

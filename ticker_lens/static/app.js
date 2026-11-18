"use strict";
const form = document.querySelector("#search");
const button = document.querySelector("#submit");
const statusBox = document.querySelector("#status");
const results = document.querySelector("#results");
const tbody = document.querySelector("#articles");
const labels = ["Bullish", "Bearish", "Neutral or mixed", "Needs review", "Unscored"];
const slug = (text) => text.toLowerCase().replaceAll(" ", "-");
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const percent = (value) => `${(value * 100).toFixed(1)}%`;

function inspect(row, questions, threshold) {
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
  panel.append(node("p", `Outlook review threshold: ${percent(threshold)} (educational default, not validated). ${row.decisions ? `Model: ${row.decisions.model}` : ""}`));
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
  tbody.replaceChildren();
  for (const row of data.rows) {
    const tr = node("tr");
    const story = node("td");
    const a = node("a", row.article.headline, "headline");
    a.href = row.article.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    story.append(a, node("p", `${row.article.source} / ${new Date(row.article.datetime * 1000).toLocaleString()} / ${row.input_depth}`, "meta"));
    story.append(inspect(row, data.questions, data.threshold));
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
  statusBox.textContent = "Retrieving news and scoring each story through Azure Foundry...";
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
    statusBox.textContent = data.rows.length
      ? `${data.rows.length} stories analyzed.${failures ? ` ${failures} could not be scored; expand those rows for the error.` : ""}`
      : "No recent news was returned for this ticker. Check the symbol or try another.";
  } catch (error) {
    statusBox.className = "error";
    statusBox.textContent = error instanceof Error ? error.message : "The request failed.";
  } finally {
    button.disabled = false;
  }
});

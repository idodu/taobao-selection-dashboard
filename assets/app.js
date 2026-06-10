const state = {
  products: [],
  filtered: [],
  rules: null,
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 1,
});

function formatRange(range) {
  if (!Array.isArray(range)) return range || "-";
  return `${currency.format(range[0])}-${currency.format(range[1])}`;
}

function scoreWidth(score) {
  return `${Math.max(8, Math.min(100, score * 10))}%`;
}

function byId(id) {
  return document.getElementById(id);
}

function renderSummary(data) {
  const products = data.products || [];
  const avgScore = products.reduce((sum, item) => sum + item.score.total, 0) / products.length;
  const topScore = Math.max(...products.map((item) => item.score.total));
  const profitCount = products.filter((item) => item.type === "利润款").length;
  const sourceCount = new Set(products.flatMap((item) => item.platforms.map((p) => p.name))).size;

  byId("summaryGrid").innerHTML = [
    ["候选品", `${products.length}个`, "每日固定输出"],
    ["平均热度", avgScore.toFixed(1), "1-10分综合模型"],
    ["最高分", topScore.toFixed(1), "优先进入上架池"],
    ["利润款", `${profitCount}个`, `${sourceCount}个平台信号`],
  ]
    .map(
      ([label, value, note]) => `
        <article class="metric">
          <span>${label}</span>
          <strong>${value}</strong>
          <span>${note}</span>
        </article>
      `,
    )
    .join("");
}

function productCard(item) {
  const platforms = item.platforms
    .map(
      (platform) => `
        <a class="platform" href="${platform.url}" target="_blank" rel="noreferrer">
          <strong><span>${platform.name}</span><span>${platform.price}</span></strong>
          <span>${platform.salesSignal}</span>
        </a>
      `,
    )
    .join("");

  return `
    <article class="product-card">
      <div class="product-image">
        <img src="${item.image}" alt="${item.name}" loading="eager" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      </div>
      <div class="product-body">
        <div>
          <div class="badge-row">
            <span class="badge">#${item.rank}</span>
            <span class="badge score">${item.score.total.toFixed(1)}分</span>
            <span class="badge warn">${item.type}</span>
          </div>
          <h3>${item.name}</h3>
          <p class="subline">${item.sku} · ${item.brandDirection}</p>
        </div>

        <div class="scoreline" aria-label="综合热度分">
          <div class="scorebar"><span style="width:${scoreWidth(item.score.total)}"></span></div>
          <p class="subline">
            跨平台${item.score.platformHeat} · 价格${item.score.priceCompetitiveness} · 利润${item.score.profitFeasibility} · 销量${item.score.salesProof} · 风险扣${item.score.riskPenalty}
          </p>
        </div>

        <div class="details">
          <div class="detail"><span>建议到手价</span><strong>${formatRange(item.suggestedPrice)}</strong></div>
          <div class="detail"><span>成本上限</span><strong>${formatRange(item.costCeiling)}</strong></div>
          <div class="detail"><span>主攻平台</span><strong>${item.primaryPlatform}</strong></div>
        </div>

        <div class="platforms">${platforms}</div>

        <div class="notes">
          <p><strong>热度依据：</strong>${item.heatEvidence}</p>
          <p><strong>上架建议：</strong>${item.listingAdvice}</p>
          <p><strong>风险提示：</strong>${item.risk}</p>
        </div>
      </div>
    </article>
  `;
}

function topCard(item) {
  return `
    <article class="top-card">
      <img src="${item.image}" alt="${item.name}" loading="eager" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      <div class="top-content">
        <div class="badge-row">
          <span class="badge">#${item.rank}</span>
          <span class="badge score">${item.score.total.toFixed(1)}分</span>
        </div>
        <h3>${item.name}</h3>
        <p class="subline">${item.sku}</p>
        <p class="subline">建议价：${formatRange(item.suggestedPrice)}</p>
      </div>
    </article>
  `;
}

function renderProducts() {
  byId("topPicks").innerHTML = state.products.slice(0, 3).map(topCard).join("");
  byId("productGrid").innerHTML = state.filtered.map(productCard).join("");
}

function populateFilters(products) {
  const categories = [...new Set(products.map((item) => item.category))].sort();
  byId("categoryFilter").innerHTML += categories
    .map((category) => `<option value="${category}">${category}</option>`)
    .join("");
}

function applyFilters() {
  const category = byId("categoryFilter").value;
  const type = byId("typeFilter").value;
  const sortBy = byId("sortBy").value;

  state.filtered = state.products.filter((item) => {
    const categoryMatch = category === "all" || item.category === category;
    const typeMatch = type === "all" || item.type === type;
    return categoryMatch && typeMatch;
  });

  state.filtered.sort((a, b) => {
    if (sortBy === "price") return a.suggestedPrice[0] - b.suggestedPrice[0];
    if (sortBy === "profit") return b.score.profitFeasibility - a.score.profitFeasibility;
    return b.score.total - a.score.total;
  });

  renderProducts();
}

function renderRules(rules) {
  byId("scoreRules").innerHTML = rules.items
    .map(
      (item) => `
        <div class="rule-item">
          <strong>${item.name} · ${item.weight}</strong>
          <p>${item.description}</p>
        </div>
      `,
    )
    .join("");
}

async function boot() {
  const response = await fetch(`data/recommendations.json?v=${Date.now()}`);
  if (!response.ok) throw new Error("无法读取选品数据");
  const data = await response.json();

  state.products = data.products;
  state.filtered = data.products;
  state.rules = data.scoreRules;

  byId("generatedAt").textContent = `生成时间：${data.generatedAtBeijing}`;
  renderSummary(data);
  populateFilters(data.products);
  renderRules(data.scoreRules);
  renderProducts();

  ["categoryFilter", "typeFilter", "sortBy"].forEach((id) => {
    byId(id).addEventListener("change", applyFilters);
  });
}

boot().catch((error) => {
  document.querySelector("main").innerHTML = `<section class="rules"><h2>数据加载失败</h2><p>${error.message}</p></section>`;
});

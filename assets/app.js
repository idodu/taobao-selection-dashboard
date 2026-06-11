const state = {
  products: [],
  filtered: [],
  avoidList: [],
  rules: null,
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 1,
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatRange(range) {
  if (!Array.isArray(range)) return escapeHtml(range || "-");
  return `${currency.format(range[0])}-${currency.format(range[1])}`;
}

function formatPercentRange(range) {
  if (!Array.isArray(range)) return "-";
  if (range.length === 2 && range[0] === range[1]) return `${range[0]}%`;
  return `${range[0]}%-${range[1]}%`;
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
  const newCount = products.filter((item) => item.statusTag === "新增").length;
  const avoidCount = (data.avoidList || []).length;
  const verified1688 = products.filter((item) => item.supply1688?.matchStatus === "exact").length;

  byId("summaryGrid").innerHTML = [
    ["单品SKU", `${products.length}个`, "每日固定输出"],
    ["平均热度", avgScore.toFixed(1), "1-10分综合模型"],
    ["最高分", topScore.toFixed(1), "优先进入上架池"],
    ["1688核验", `${verified1688}/${products.length}`, verified1688 ? "已接入官方单SKU价" : "等待TOP应用密钥"],
    ["风控", `${newCount}新/${avoidCount}暂缓`, "避免误上高风险品"],
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

function renderOperatorGuide(data) {
  const guide = data.operatorGuide || [];
  const rules = data.trialRules || [];
  byId("operatorGuide").innerHTML = `
    <div>
      <p class="eyebrow">Daily workflow</p>
      <h2>店主每日10分钟操作流程</h2>
    </div>
    <div class="operator-steps">
      ${guide
        .map(
          (item, index) => `
            <article class="step-card">
              <span>${index + 1}</span>
              <p>${escapeHtml(item)}</p>
            </article>
          `,
        )
        .join("")}
    </div>
    <div class="trial-rules">
      ${rules.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
    </div>
  `;
}

function statusBadges(item) {
  const statusClass = item.statusTag === "新增" ? "new" : item.statusTag === "昨日品" ? "yesterday" : "returning";
  const countBadge = item.appearanceCount > 1 ? `<span class="badge repeat">累计${item.appearanceCount}次</span>` : "";
  return `
    <span class="badge ${statusClass}">${escapeHtml(item.statusTag)}</span>
    ${countBadge}
  `;
}

function platformCard(platform) {
  return `
    <a class="platform" href="${escapeHtml(platform.url)}" target="_blank" rel="noreferrer">
      <strong><span>${escapeHtml(platform.name)}</span><span>${escapeHtml(platform.price)}</span></strong>
      <span class="match">${escapeHtml(platform.matchType || "参考价")}</span>
      <span>${escapeHtml(platform.salesSignal)}</span>
    </a>
  `;
}

function scoreText(item) {
  const score = item.score;
  return [
    `跨平台${score.platformHeat}`,
    `价格${score.priceCompetitiveness}`,
    `利润${score.profitFeasibility}`,
    `销量${score.salesProof}`,
    `复购${score.repeatPurchase}`,
    `差异${score.differentiation}`,
    `风险扣${score.riskPenalty}`,
  ].join(" · ");
}

function supply1688Panel(item) {
  const supply = item.supply1688 || {};
  const verified = supply.matchStatus === "exact" && Number.isFinite(supply.lowestPrice);
  const href = verified ? supply.offerUrl : supply.searchUrl;
  const price = verified ? currency.format(supply.lowestPrice) : "待核验";
  const meta = verified
    ? `${supply.moq ? `起订量 ${escapeHtml(supply.moq)}${escapeHtml(supply.unit || "件")} · ` : "起订量需商品页确认 · "}核验时间 ${escapeHtml(supply.verifiedAt)}`
    : "未取得可审计的同品牌同规格报价，不展示推测价格";

  return `
    <a class="supply-panel ${verified ? "verified" : "pending"}" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">
      <div>
        <span class="supply-label">1688 单SKU最低价</span>
        <strong>${price}</strong>
      </div>
      <div class="supply-meta">
        <span class="badge ${verified ? "score" : "warn"}">${verified ? "精确匹配 已核验" : "待核验"}</span>
        <span>${meta}</span>
      </div>
    </a>
  `;
}

function productCard(item) {
  const platforms = item.platforms.map(platformCard).join("");
  const sourceLabel = `${item.sourcePlatform} ${item.sourceSkuId}`;

  return `
    <article class="product-card">
      <div class="product-image">
        <img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="eager" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      </div>
      <div class="product-body">
        <div>
          <div class="badge-row">
            <span class="badge">#${item.rank}</span>
            <span class="badge score">${item.score.total.toFixed(1)}分</span>
            <span class="badge warn">${escapeHtml(item.type)}</span>
            ${statusBadges(item)}
          </div>
          <h3>${escapeHtml(item.name)}</h3>
          <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
        </div>

        <div class="scoreline" aria-label="综合热度分">
          <div class="scorebar"><span style="width:${scoreWidth(item.score.total)}"></span></div>
          <p class="subline">${scoreText(item)}</p>
        </div>

        <div class="details">
          <div class="detail"><span>建议售价</span><strong>${formatRange(item.suggestedPrice)}</strong></div>
          <div class="detail"><span>成本上限</span><strong>${formatRange(item.costCeiling)}</strong></div>
          <div class="detail"><span>预计毛利率</span><strong>${formatPercentRange(item.estimatedGrossProfitRate)}</strong><small>${escapeHtml(item.marginBasis)}</small></div>
          <div class="detail"><span>平台低价</span><strong>${item.platformLowestPrice ? currency.format(item.platformLowestPrice) : "内容参考"}</strong></div>
        </div>

        ${supply1688Panel(item)}

        <div class="platforms">${platforms}</div>

        <div class="notes">
          <p><strong>源商品链接：</strong><a class="source-link" href="${escapeHtml(item.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(sourceLabel)}</a></p>
          <p><strong>热度依据：</strong>${escapeHtml(item.heatEvidence)}</p>
          <p><strong>上架建议：</strong>${escapeHtml(item.listingAdvice)}</p>
          <p><strong>风险提示：</strong>${escapeHtml(item.risk)}</p>
          <p><strong>1688口径：</strong>${escapeHtml(item.supply1688.note)}</p>
        </div>
      </div>
    </article>
  `;
}

function topCard(item) {
  return `
    <article class="top-card">
      <img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="eager" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      <div class="top-content">
        <div class="badge-row">
          <span class="badge">#${item.rank}</span>
          <span class="badge score">${item.score.total.toFixed(1)}分</span>
          ${statusBadges(item)}
        </div>
        <h3>${escapeHtml(item.name)}</h3>
        <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
        <p class="subline">建议售价：${formatRange(item.suggestedPrice)}</p>
        <p class="subline">1688：${item.supply1688?.lowestPrice ? currency.format(item.supply1688.lowestPrice) : "待核验"}</p>
      </div>
    </article>
  `;
}

function avoidCard(item) {
  return `
    <article class="avoid-card">
      <div class="badge-row">
        <span class="badge danger">${escapeHtml(item.statusTag || "暂缓")}</span>
        <span class="badge warn">${escapeHtml(item.category || "风控")}</span>
      </div>
      <h3>${escapeHtml(item.name)}</h3>
      <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
      <p><strong>回避原因：</strong>${escapeHtml(item.avoidReason)}</p>
      <p><strong>后续观察：</strong>${escapeHtml(item.revisitCondition)}</p>
      <a class="source-link" href="${escapeHtml(item.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(item.sourcePlatform)} ${escapeHtml(item.sourceSkuId)}</a>
    </article>
  `;
}

function renderProducts() {
  byId("topPicks").innerHTML = state.products.slice(0, 3).map(topCard).join("");
  byId("productGrid").innerHTML = state.filtered.map(productCard).join("");
  byId("avoidGrid").innerHTML = state.avoidList.map(avoidCard).join("");
}

function populateFilters(products) {
  const categories = [...new Set(products.map((item) => item.category))].sort();
  byId("categoryFilter").innerHTML += categories
    .map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`)
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
    if (sortBy === "repeat") return b.score.repeatPurchase - a.score.repeatPurchase;
    return b.score.total - a.score.total;
  });

  renderProducts();
}

function renderRules(rules) {
  byId("scoreRules").innerHTML = rules.items
    .map(
      (item) => `
        <div class="rule-item">
          <strong>${escapeHtml(item.name)} · ${escapeHtml(item.weight)}</strong>
          <p>${escapeHtml(item.description)}</p>
        </div>
      `,
    )
    .join("");
}

async function boot() {
  const response = await fetch(`data/recommendations.json?v=${Date.now()}`);
  if (!response.ok) throw new Error("无法读取选品数据");
  const data = await response.json();

  state.products = data.products || [];
  state.filtered = data.products || [];
  state.avoidList = data.avoidList || [];
  state.rules = data.scoreRules;

  byId("generatedAt").textContent = `生成时间：${data.generatedAtBeijing}`;
  renderSummary(data);
  renderOperatorGuide(data);
  populateFilters(state.products);
  renderRules(data.scoreRules);
  renderProducts();

  ["categoryFilter", "typeFilter", "sortBy"].forEach((id) => {
    byId(id).addEventListener("change", applyFilters);
  });
}

boot().catch((error) => {
  document.querySelector("main").innerHTML = `<section class="rules"><h2>数据加载失败</h2><p>${escapeHtml(error.message)}</p></section>`;
});

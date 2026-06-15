const state = {
  products: [],
  filtered: [],
  trackingProducts: [],
  radarProducts: [],
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

function formatMoney(value) {
  return Number.isFinite(value) ? currency.format(value) : "—";
}

function formatCount(value) {
  return Number.isFinite(value) ? new Intl.NumberFormat("zh-CN").format(value) : "—";
}

function marketStatus(platform) {
  if (platform.matchStatus === "exact" && platform.freshnessStatus === "fresh") return ["已核验", "verified"];
  if (platform.matchStatus === "exact" && platform.freshnessStatus === "aging") return ["数据老化", "aging"];
  if (platform.freshnessStatus === "stale") return ["已过期", "stale"];
  if (platform.status === "not-configured") return ["待授权", "pending"];
  if (platform.status === "no-exact-match") return ["无精确匹配", "pending"];
  if (platform.status === "error") return ["刷新失败", "stale"];
  return ["待核验", "pending"];
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
  const avoidCount = (data.avoidList || []).length;
  const verified1688 = products.filter((item) => item.supply1688?.matchStatus === "exact").length;
  const verifiedMarket = products.reduce(
    (count, item) =>
      count +
      item.platforms.filter(
        (platform) =>
          platform.matchStatus === "exact" &&
          ["fresh", "aging"].includes(platform.freshnessStatus),
      ).length,
    0,
  );

  byId("summaryGrid").innerHTML = [
    ["候选池", `${data.catalogSize || products.length}个`, `今日推荐${products.length}个`],
    ["平均热度", avgScore.toFixed(1), "1-10分综合模型"],
    ["官方市场核验", `${verifiedMarket}/${products.length * 3}`, "淘宝·京东·抖音"],
    ["1688核验", `${verified1688}/${products.length}`, verified1688 ? "已接入官方单SKU价" : "等待TOP应用密钥"],
    ["今日换新", `${data.changeSummary?.replacementCount ?? 0}个`, `与昨日重合${data.changeSummary?.overlapWithPrevious ?? 0}个`],
    ["风控", `${avoidCount}暂缓`, "高频商品自动冷却"],
  ]
    .map(
      ([label, value, note]) => `
        <article class="metric">
          <span>${label}</span>
          <strong class="metric-value" data-final-value="${escapeHtml(value)}">${value}</strong>
          <span>${note}</span>
        </article>
      `,
    )
    .join("");
}

function renderTodayBrief(data) {
  const summary = data.changeSummary || {};
  const highlights = summary.highlights || [];
  byId("todayBrief").innerHTML = `
    <div class="brief-lead">
      <div>
        <p class="eyebrow">Today changed</p>
        <h2>${escapeHtml(summary.headline || "今日选品已更新")}</h2>
      </div>
      <div class="freshness-ring" aria-label="今日换新数量">
        <strong data-final-value="${summary.replacementCount ?? 0}">${summary.replacementCount ?? 0}</strong>
        <span>款换新</span>
      </div>
    </div>
    <div class="brief-highlights">
      ${highlights.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
    </div>
    <div class="next-refresh">
      <span>下次更新</span>
      <strong id="refreshCountdown">计算中</strong>
    </div>
  `;
}

function updateRefreshCountdown() {
  const target = byId("refreshCountdown");
  if (!target) return;
  const now = new Date();
  const next = new Date(now);
  next.setHours(10, 0, 0, 0);
  if (now >= next) next.setDate(next.getDate() + 1);
  const totalMinutes = Math.max(0, Math.floor((next - now) / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  target.textContent = `${hours}小时${minutes}分`;
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
  const [statusLabel, statusClass] = marketStatus(platform);
  const verifiedAt = platform.verifiedAt
    ? new Date(platform.verifiedAt).toLocaleString("zh-CN", { hour12: false })
    : "—";
  return `
    <a class="platform market-${statusClass}" href="${escapeHtml(platform.url)}" target="_blank" rel="noreferrer">
      <div class="platform-head">
        <span class="platform-name">${escapeHtml(platform.name)}</span>
        <span class="market-status">${statusLabel}</span>
      </div>
      <strong class="market-price">${escapeHtml(platform.price)}</strong>
      <div class="market-facts">
        <span><i>标价</i><b>${formatMoney(platform.listPrice)}</b></span>
        <span><i>券额</i><b>${formatMoney(platform.couponAmount)}</b></span>
        <span><i>30天销量</i><b>${formatCount(platform.sales30d)}</b></span>
        <span><i>累计评价</i><b>${formatCount(platform.reviewCount)}</b></span>
      </div>
      <span class="match">${escapeHtml(platform.matchType)}</span>
      <span class="market-time">核验 ${escapeHtml(verifiedAt)}</span>
    </a>
  `;
}

function selectionBadge(item) {
  return item.selectionReason
    ? `<span class="badge selection">${escapeHtml(item.selectionReason)}</span>`
    : "";
}

function platformEvidence(platform) {
  return `
    <a class="evidence-row" href="${escapeHtml(platform.url)}" target="_blank" rel="noreferrer">
      <strong>${escapeHtml(platform.name)}</strong>
      <span>${escapeHtml(platform.salesSignal)}</span>
    </a>
  `;
}

function scoreText(item) {
  const score = item.score;
  return [
    `跨平台${score.platformHeat}`,
    `价格${score.priceCompetitiveness}${score.priceEvidenceAvailable ? "" : "（无官方价）"}`,
    `利润${score.profitFeasibility}`,
    `销量${score.salesProof}${score.salesEvidenceAvailable ? "" : "（无官方销量）"}`,
    `复购${score.repeatPurchase}`,
    `差异${score.differentiation}`,
    `风险扣${score.riskPenalty}`,
  ].join(" · ");
}

function supply1688Panel(item) {
  const supply = item.supply1688 || {};
  const verified = supply.matchStatus === "exact" && Number.isFinite(supply.lowestPrice);
  const freshness = supply.freshnessStatus || "unverified";
  const freshnessLabel = freshness === "fresh" ? "48小时内" : freshness === "aging" ? "需复核" : freshness === "stale" ? "已过期" : "待核验";
  const href = verified ? supply.offerUrl : supply.searchUrl;
  const price = verified ? currency.format(supply.lowestPrice) : "待核验";
  const meta = verified
    ? `${supply.moq ? `起订量 ${escapeHtml(supply.moq)}${escapeHtml(supply.unit || "件")} · ` : "起订量需商品页确认 · "}核验时间 ${escapeHtml(supply.verifiedAt)}`
    : "未取得可审计的同品牌同规格报价，不展示推测价格";

  return `
    <a class="supply-panel ${verified ? "verified" : "pending"}" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">
      <div>
        <span class="supply-label">1688 单SKU价</span>
        <strong>${price}</strong>
      </div>
      <div class="supply-meta">
        <span class="badge ${verified && freshness === "fresh" ? "score" : "warn"}">${verified ? `精确匹配 · ${freshnessLabel}` : "待核验"}</span>
        <span class="supply-detail">${meta}</span>
      </div>
    </a>
  `;
}

function productCard(item) {
  const platforms = item.platforms.map(platformCard).join("");
  const platformEvidenceRows = item.platforms.map(platformEvidence).join("");
  const sourceLabel = `${item.sourcePlatform} ${item.sourceSkuId}`;

  return `
    <article class="product-card">
      <div class="product-image">
        <img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="eager" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      </div>
      <div class="product-body">
        <div class="product-heading">
          <div class="badge-row">
            <span class="badge">#${item.rank}</span>
            <span class="badge score">${item.score.total.toFixed(1)}分</span>
            <span class="badge warn">${escapeHtml(item.type)}</span>
            ${selectionBadge(item)}
            ${statusBadges(item)}
          </div>
          <h3>${escapeHtml(item.name)}</h3>
          <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
        </div>

        <div class="scoreline" aria-label="综合热度分">
          <div class="scorebar"><span data-score-fill="${item.score.total}" style="width:${scoreWidth(item.score.total)}"></span></div>
        </div>

        <div class="details">
          <div class="detail"><span>建议售价</span><strong>${formatRange(item.suggestedPrice)}</strong></div>
          <div class="detail"><span>预计毛利率</span><strong>${formatPercentRange(item.estimatedGrossProfitRate)}</strong></div>
          <div class="detail"><span>官方预估最低到手价</span><strong>${item.platformLowestPrice ? currency.format(item.platformLowestPrice) : "待授权"}</strong></div>
          <div class="detail"><span>成本上限</span><strong>${formatRange(item.costCeiling)}</strong></div>
        </div>

        ${supply1688Panel(item)}

        <div class="platforms">${platforms}</div>

        <details class="product-more">
          <summary><span>完整依据与上架建议</span><span class="summary-icon" aria-hidden="true">＋</span></summary>
          <div class="expanded-content">
            <div class="score-breakdown">
              <strong>评分明细</strong>
              <p>${scoreText(item)}</p>
            </div>
            <div class="platform-evidence">${platformEvidenceRows}</div>
            <div class="notes">
              <p><strong>源商品：</strong><a class="source-link" href="${escapeHtml(item.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(sourceLabel)}</a></p>
              <p><strong>热度依据：</strong>${escapeHtml(item.heatEvidence)}</p>
              <p><strong>上架建议：</strong>${escapeHtml(item.listingAdvice)}</p>
              <p><strong>风险提示：</strong>${escapeHtml(item.risk)}</p>
              <p><strong>成本口径：</strong>${escapeHtml(item.marginBasis)}</p>
              <p><strong>1688口径：</strong>${escapeHtml(item.supply1688.note)}</p>
            </div>
          </div>
        </details>
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
          ${selectionBadge(item)}
          ${statusBadges(item)}
        </div>
        <h3>${escapeHtml(item.name)}</h3>
        <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
        <p class="subline">建议售价：${formatRange(item.suggestedPrice)}</p>
        <p class="subline">官方预估最低到手：${item.platformLowestPrice ? currency.format(item.platformLowestPrice) : "待授权"}</p>
        <p class="subline">1688：${item.supply1688?.lowestPrice ? currency.format(item.supply1688.lowestPrice) : "待核验"}</p>
      </div>
    </article>
  `;
}

function signalCard(item, mode) {
  const label = mode === "tracking" ? "持续跟踪" : "新品雷达";
  const reason = mode === "tracking" ? item.trackingReason : item.radarReason;
  return `
    <article class="signal-card">
      <img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" loading="lazy" onerror="this.onerror=null;this.src='assets/placeholder.svg';">
      <div>
        <div class="badge-row">
          <span class="badge ${mode === "tracking" ? "returning" : "new"}">${label}</span>
          <span class="badge score">${item.score.total.toFixed(1)}分</span>
        </div>
        <h3>${escapeHtml(item.name)}</h3>
        <p class="subline">${escapeHtml(item.brand)} · ${escapeHtml(item.sku)}</p>
        <p class="signal-reason">${escapeHtml(reason)}</p>
        <a class="source-link" href="${escapeHtml(item.sourceUrl)}" target="_blank" rel="noreferrer">查看源商品</a>
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

function renderProducts(reason = "update") {
  byId("topPicks").innerHTML = state.products.slice(0, 3).map(topCard).join("");
  byId("productGrid").innerHTML = state.filtered.map(productCard).join("");
  byId("trackingGrid").innerHTML = state.trackingProducts.map((item) => signalCard(item, "tracking")).join("");
  byId("radarGrid").innerHTML = state.radarProducts.map((item) => signalCard(item, "radar")).join("");
  byId("avoidGrid").innerHTML = state.avoidList.map(avoidCard).join("");
  updateRailControls("tracking");
  updateRailControls("radar");
  syncDetailsToggle();
  window.dispatchEvent(new CustomEvent("dashboard:products-updated", { detail: { reason } }));
}

function railElements(mode) {
  return {
    rail: byId(`${mode}Grid`),
    counter: byId(`${mode}Counter`),
    previous: byId(`${mode}Prev`),
    next: byId(`${mode}Next`),
  };
}

function updateRailControls(mode) {
  const { rail, counter, previous, next } = railElements(mode);
  if (!rail || !counter || !previous || !next) return;

  const cards = [...rail.querySelectorAll(".signal-card")];
  if (!cards.length) {
    counter.textContent = "0 个";
    previous.disabled = true;
    next.disabled = true;
    return;
  }

  const cardWidth = cards[0].getBoundingClientRect().width;
  const gap = Number.parseFloat(getComputedStyle(rail).columnGap) || 0;
  const step = cardWidth + gap;
  const start = Math.min(cards.length - 1, Math.max(0, Math.round(rail.scrollLeft / step)));
  const visibleCount = Math.max(1, Math.floor((rail.clientWidth + gap) / step));
  const end = Math.min(cards.length, start + visibleCount);

  counter.textContent = `${start + 1}–${end} / 共 ${cards.length} 个`;
  previous.disabled = rail.scrollLeft <= 2;
  next.disabled = rail.scrollLeft + rail.clientWidth >= rail.scrollWidth - 2;
}

function moveRail(mode, direction) {
  const { rail } = railElements(mode);
  if (!rail) return;
  rail.scrollBy({
    left: direction * Math.max(280, rail.clientWidth * 0.88),
    behavior: "smooth",
  });
  window.dispatchEvent(new CustomEvent("dashboard:rail-move", { detail: { mode, direction } }));
}

function bindRailControls(mode) {
  const { rail, previous, next } = railElements(mode);
  if (!rail || !previous || !next) return;
  previous.addEventListener("click", () => moveRail(mode, -1));
  next.addEventListener("click", () => moveRail(mode, 1));
  rail.addEventListener("scroll", () => updateRailControls(mode), { passive: true });
}

function syncDetailsToggle() {
  const toggle = byId("detailsToggle");
  if (!toggle) return;
  const details = [...document.querySelectorAll(".product-more")];
  const allOpen = details.length > 0 && details.every((item) => item.open);
  toggle.setAttribute("aria-pressed", String(allOpen));
  toggle.innerHTML = `<span aria-hidden="true">${allOpen ? "−" : "＋"}</span>${allOpen ? "收起全部详情" : "展开全部详情"}`;
}

function toggleAllDetails() {
  const details = [...document.querySelectorAll(".product-more")];
  const shouldOpen = !details.every((item) => item.open);
  details.forEach((item) => {
    item.open = shouldOpen;
  });
  syncDetailsToggle();
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

  renderProducts("filter");
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
  state.trackingProducts = data.trackingProducts || [];
  state.radarProducts = data.radarProducts || [];
  state.avoidList = data.avoidList || [];
  state.rules = data.scoreRules;

  byId("generatedAt").textContent = `生成时间：${data.generatedAtBeijing}`;
  renderSummary(data);
  renderTodayBrief(data);
  updateRefreshCountdown();
  window.setInterval(updateRefreshCountdown, 60000);
  renderOperatorGuide(data);
  populateFilters(state.products);
  renderRules(data.scoreRules);
  renderProducts("initial");
  bindRailControls("tracking");
  bindRailControls("radar");
  window.addEventListener("resize", () => {
    updateRailControls("tracking");
    updateRailControls("radar");
  });

  ["categoryFilter", "typeFilter", "sortBy"].forEach((id) => {
    byId(id).addEventListener("change", applyFilters);
  });
  byId("detailsToggle").addEventListener("click", toggleAllDetails);
  byId("productGrid").addEventListener("toggle", syncDetailsToggle, true);
  document.body.dataset.dashboardReady = "true";
  window.dispatchEvent(new CustomEvent("dashboard:ready", { detail: { data } }));
}

boot().catch((error) => {
  document.querySelector("main").innerHTML = `<section class="rules"><h2>数据加载失败</h2><p>${escapeHtml(error.message)}</p></section>`;
});

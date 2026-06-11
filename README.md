# 淘宝家清个护 / 日化纸品单品SKU选品看板

这是一个静态可视化选品系统，用于每天展示家清个护、日化纸品方向的 10 个候选单品 SKU。每个推荐项必须是单一品牌、单一规格、可追溯源商品链接的具体 SKU，并展示商品图片、各平台参考低价、公开销量/评论信号、建议售价、1688 单 SKU 最低价状态、预计毛利率和 1-10 分综合热度评分。

系统面向零经验店主：每天只需要先看 Top3，再核对真实供货价和履约条件，最后决定上架或暂缓。

## 每日 10 分钟操作流程

1. 看：先看今日 Top3 和热度分，只处理具体 SKU，不处理泛品类。
2. 核：核对真实供货价、运费模板、保质期、品牌授权/进货凭证。
3. 上：真实成本低于供货价参考时再上架；高于参考值则暂缓或改组合装。
4. 72 小时：看曝光、点击、收藏加购；无曝光先改标题和主图。
5. 7 天：看转化、退款、毛利；低效 SKU 淘汰或降为活动品。

## 运行方式

- 本地预览：在仓库根目录运行 `python -m http.server 8080`，访问 `http://localhost:8080`。
- 生成数据：运行 `python scripts/generate_daily_data.py`。
- 健康检查：运行 `python scripts/validate_dashboard.py`。
- 云端运营：GitHub Actions 工作流 `.github/workflows/daily-update.yml` 每天 `02:00 UTC` 运行，即北京时间 `10:00`。
- 发布方式：GitHub Pages 使用 Actions 部署，电脑关机不影响每日生成和发布。

## SKU 口径

- 商品池维护在 `data/product_catalog.json`。
- 每条推荐记录必须包含 `brand`、`name`、`sku`、`sourceUrl`、`image`、`platforms`、`suggestedPrice` 和评分输入。
- 不再使用“品牌方向”字段，不允许一条推荐里出现多个可选品牌。
- 同一平台找不到完全同款时，平台价用“近似同规格参考价”标注，不冒充精确同款。
- `avoidList` 用于今日暂缓/回避 SKU，每项仍必须是单一品牌、单一规格、可追溯源商品链接。

## 评分规则

综合热度分为 1-10 分，由 `scripts/generate_daily_data.py` 计算。

总分 = 跨平台热度 30% + 价格竞争力 20% + 利润可行性 20% + 销量/评论信号 10% + 复购率 10% + 差异化空间 5% + 上架可操作性 5% - 风险扣分。

- 跨平台热度：淘宝/天猫、京东、抖音、小红书出现榜单、热词、内容种草或行业报告信号越多，得分越高。
- 价格竞争力：建议售价越接近同品牌同规格或近似规格的主流低价带，且不牺牲毛利，得分越高。
- 利润可行性：有已核验的 1688 单 SKU 精确报价时按真实最低公开阶梯价计算；否则按 `建议售价 * 78%` 显示成本上限估算，并明确标记为非真实供货价。
- 销量/评论信号：公开评论量、榜单名次、销量口径、达人带货或内容互动信号越强，得分越高。
- 复购率：纸品、清洁剂、洗护等消耗速度快、复购周期短的 SKU 得分更高。
- 差异化空间：能通过组合装、赠品、标题场景、主图卖点避开官方同款硬碰的 SKU 得分更高。
- 上架可操作性：经销现货、标准品牌 SKU、履约稳定、资质风险低、售后可控的 SKU 得分更高。
- 风险扣分：控价、重货运费、液体破损、资质/功效合规、品控投诉等会扣分。

## 上榜与风控

系统维护 `data/selection_history.json`：

- `新增`：历史上首次进入每日 10 个候选。
- `昨日品`：前一天已经上榜，今天继续保留。
- `回归品`：历史上出现过，但昨天未上榜，今天重新进入候选。
- `累计N次`：同一个 SKU 累计进入每日候选的次数。

页面同时展示“今日暂缓上架 SKU”，用于提醒暂不建议上架的具体商品及后续观察条件。典型原因包括价格战、重货运费、控价投诉、功效合规、保质期风险。

## 试款约束

- 单 SKU 首批试款成本建议控制在 ￥200-￥500。
- 液体和纸品重货必须先核算快递阶梯价、破损率和偏远地区策略。
- 不具备授权、凭证、保质期可控条件的 SKU 不进入上架池。

## 数据产物

- 1688 已核验价格缓存：`data/1688_supply_prices.json`
- 每日生成结果：`data/recommendations.json`
- 每日上榜历史：`data/selection_history.json`
- 每日归档：`docs/daily/YYYY-MM-DD.md`

## 1688 价格接入

系统只接受满足以下条件的 1688 报价：同一品牌、同一完整规格、单独 SKU、正数最低价、正数起订量、可访问的 `1688.com` 商品链接和核验时间。没有满足这些条件的数据时，页面显示“待核验”，不会生成虚假最低价。

云端每天先运行 `scripts/sync_1688_prices.py`，再生成看板。首选数据源为淘宝开放平台官方接口 `alibaba.open.search.daixiao.offer.get`：按关键词搜索 1688 代销市场、按价格升序取回候选，然后只有标题同时命中品牌及全部规格词组的商品才会被认定为精确 SKU。

GitHub 仓库需要配置：

- `TOP_APP_KEY`：淘宝开放平台应用 AppKey。
- `TOP_APP_SECRET`：淘宝开放平台应用 AppSecret。

该搜索 API 不需要买家 `session` 授权，但所有 TOP API 请求仍必须使用 AppKey/AppSecret 签名。系统使用官方支持的 HMAC-MD5 签名，不在仓库或日志中输出密钥。

如果暂时无法完成 TOP 开发者认证，可使用 ElimAPI 的 1688 授权搜索服务。其免费档公开说明为每月 200 次请求，配置一个 GitHub Secret 即可：

- `ELIM_API_KEY`：ElimAPI 控制台生成的 API Key，系统通过官方要求的 `x-api-key` 请求头使用。
- `ELIM_ACCESS_TOKEN`：可选。通过登录接口获得的短期 JWT，仅在未配置 API Key 时使用。

系统优先级为 `TOP_APP_KEY/TOP_APP_SECRET` → `ELIM_API_KEY` → 自定义授权报价源。ElimAPI 搜索结果会同时比较常规价、促销价、批发代销价和零售价，取精确标题匹配商品中的最低值，并记录实际采用的价格字段。

为适配每月 200 次的免费额度，云端默认每天按“最久未检查优先”刷新 5 个 SKU，10 个 SKU 最长约 48 小时轮换一遍，月请求量约 150 次。旧报价会保留核验时间：

- 48 小时内：`48小时内`
- 48 小时至 7 天：`需复核`
- 超过 7 天：`已过期`

在 GitHub Actions 手动运行时勾选 `full_refresh`，可一次刷新全部 10 个 SKU，适合首次接入或临时复核。

配置路径：GitHub 仓库 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`。两个 Secret 配置完成后，手动运行一次 `Daily product selection update`，页面的“1688核验”指标会显示成功匹配的 SKU 数量。

也可以在仓库根目录运行以下脚本完成 ElimAPI 的安全配置和首次全量刷新：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure_1688_provider.ps1
```

脚本会隐藏输入内容，将密钥直接写入 GitHub Secret `ELIM_API_KEY`，随后触发全部 10 个 SKU 的首次刷新并等待 Pages 部署完成。密钥不会写入本地文件或 Git 历史。

本地测试可参考 `.env.1688.example` 设置环境变量后运行：

```powershell
$env:TOP_APP_KEY="..."
$env:TOP_APP_SECRET="..."
python scripts/sync_1688_prices.py --provider top
python scripts/generate_daily_data.py
python scripts/validate_dashboard.py
```

如果已有 ERP 或经销商授权报价服务，也可继续使用备用数据源：

- `SUPPLY_1688_FEED_URL`：授权 JSON 数据源地址。
- `SUPPLY_1688_FEED_TOKEN`：可选 Bearer Token。

数据源格式：

```json
{
  "updatedAt": "2026-06-11T10:00:00+08:00",
  "items": {
    "jd-100145357766-vinda-wet-toilet-80x5": {
      "lowestPrice": 18.8,
      "moq": 2,
      "unit": "件",
      "matchStatus": "exact",
      "matchedTitle": "维达湿厕纸80片5包",
      "offerId": "1688商品ID",
      "offerUrl": "https://detail.1688.com/offer/商品ID.html",
      "verifiedAt": "2026-06-11T09:55:00+08:00"
    }
  }
}
```

当前仓库未配置 TOP 应用凭证，因此系统会诚实显示“待核验”。直接抓取 1688 页面无法稳定保证登录态、阶梯价和 SKU 匹配准确，不适合作为无人值守的每日价格源。

官方依据：

- [代销市场商品搜索服务](https://open.alitrip.com/docs/api.htm?apiId=26839)
- [TOP API 公共参数与签名算法](https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1)
- [ElimAPI 1688产品搜索和价格字段说明](https://elim.asia/zh/guides/product/)

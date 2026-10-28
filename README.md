# freebie-weekly

每周一次，把「本地这周能白嫖或低价捡漏的活动」整理成一份**能照着去**的清单：免费展览、免费音乐会、对外开放的校园/场馆活动、低价体验（原价几百，现在几十）。

不是又一个爬虫框架。它只干三件事：找信源、抽字段、把不确定的地方标出来。

## 为什么是这个形状

需求探针阶段实测出来的三条硬约束，直接决定了架构：

| 实测 | 结果 | 架构后果 |
|---|---|---|
| bing / duckduckgo / sogou 同时打 | 当前出口 IP 下三个通道全被封（302 / 连不上 / antispider） | 搜索层必须多引擎 + 可手动喂 URL，不能赌单一渠道 |
| 抓 `mp.weixin.qq.com` 短链 / 无 `chksm` 的链接 | 落验证页「环境异常」 | 只认带 `chksm` 的长链；抓不到就明说，不猜 |
| 活动行页面正文没有价格 | `"PriceStr":"免费"` 藏在页面内嵌 JSON 里 | 正文抽不到时读内嵌价格，并标注「价格取自页面内嵌数据」 |

**一条错的价格比少一条严重得多**——用户会因此白跑一趟。所以这里的默认动作是标注「未标时间」「价格取自页面内嵌数据」，不是编一个看起来合理的时间。

### 关于「怎么找到链接」的实测结论（v0.1 跑完才确认的）

| 发现通道 | 实测 | 能不能当主力 |
|---|---|---|
| bing | 能连、能解析出 10 条，但中文活动词查询返回的是景点/旅游页；`site:mp.weixin.qq.com` 对 bing 无效 | ❌ |
| 搜狗（`type=2`） | 能出公众号文章，但连续 20~25 次后 antispider，之后全封 | ⚠️ 少量补充 |
| duckduckgo | 直连超时，HTML 端点也不通 | ❌ |
| **harness 的 `web_search`** | `site:mp.weixin.qq.com <城市> 免费 音乐会` 实测 8/8 命中真文章 | ✅ **主路径** |
| 配置 `sources:` 固定信源 | 直接抓官网栏目页/活动页，结果可复现 | ✅ 稳定兜底 |
| we-mp-rss 订阅 | 能按号盯，需要 docker + 扫码 | ✅ 要「按号盯」时用 |

所以周报现实里跑两条路：**harness 用 `web_search` 找链接 → `--urls` 喂进来**，或者 **`sources:` 维护几个固定信源**。
CLI 自带搜索留着当兜底，它失败时会如实写进「本周没能覆盖」，不会假装跑通了。

## 安装

零依赖，Python 3.9+，只要标准库就能跑：

```bash
cd freebie-weekly
python3 -m pip install -e .          # 或者直接 PYTHONPATH=src python3 -m freebie.cli
```

要读 YAML 配置再装可选依赖：`pip install -e ".[yaml]"`。

## 用法

城市是**参数**，不是写死的：`--city` 给什么城市就跑什么城市，代码里没有任何城市名。

```bash
# 自检：搜索引擎通不通、WeRSS 有没有跑起来
freebie doctor

# 跑一轮（唯一必填的参数是城市）
freebie run --city 北京
freebie run --city 成都          # 没备信源也有默认行为：退回通用搜索词

# 看哪些城市已经备好信源
freebie cities
freebie seeds init --city 成都   # 生成一个待填的城市 yaml，加城市不用改代码

# 手动喂链接（搜索被风控时的保底路径，也是验证抽字段最快的办法）
freebie run --city 北京 \
  --urls "https://peking.bjd.com.cn/content/s6ac9ffb0e4b0e42f8f01637d.html" \
         "https://item.btime.com/44p6p8j9cmi9mtb5dtpb8h9risj"

freebie run --city 北京 --free-only --max-price 50   # 只要免费的 / 低价上限 50
freebie run --city 北京 --json                       # 给下游或 LLM 用
freebie run --city 北京 --no-seeds                   # 忽略 seeds 里的城市信源，强制走搜索
freebie discover --city 北京                          # 建本地账号清单用：按城市搜候选公众号
```

退出码：`0` 有结果，`2` 没结果（定时任务里据此判断要不要惊动人）。

### 城市是怎么决定抓哪儿的

三层，逐层降级，每层都会在报告末尾写明用了哪层：

| 顺序 | 来源 | 触发条件 |
|---|---|---|
| 1 | `--urls` 手动链接 | 你给了就用，什么都不搜 |
| 2 | `seeds/<城市>.yaml` 的 `channels:` | 有这个城市的种子文件就自动用，不跑搜索 |
| 3 | 通用搜索词（`{city}` 替换成城市名） | 没有种子文件时兜底；搜不到就如实报「没找到可抓的链接」 |

所以「支持哪些城市」由 `seeds/` 目录决定，不由代码决定。加一个城市 = 加一个 yaml，或者 `seeds init` 生成后填 URL。

## 输出长什么样

```
【北京 · 10.28 本地羊毛 3 条】

★ 本周最值
1. 大戏看北京·2026北京国际戏剧展演季丨戏聚北京，起舞海淀！街头、商圈、校园、剧院全都有——
   免费 · 需预约 · 11.1/11.8 · 先到先得 · 民族剧院
   本次活动由海淀区委宣传部联合区文联、区文化和旅游局组织开展…
   → https://peking.bjd.com.cn/content/s6ac9ffb0e4b0e42f8f01637d.html
2. 通州「绿心花朝」游园会
   免费 · 10.31-11.1/11.17 · 城市绿心森林公园
   → https://item.btime.com/44p6p8j9cmi9mtb5dtpb8h9risj

【本周没能覆盖 / 需要你确认】
- 使用 seeds/beijing.yaml 的 4 个北京信源（不跑搜索）

—— 候选 4 个链接，抓到 4 篇正文，最后留下 3 条。
—— 过滤原因：超出窗口 1。
```

页脚会写清「这轮抓了几个、丢了几个、为什么丢」——**没覆盖到什么**和覆盖到什么一样重要。

## 每周定时

macOS/Linux cron（周一 9:00，城市换成你自己的）：

```cron
0 9 * * 1  cd /path/to/freebie-weekly && PYTHONPATH=src /usr/bin/python3 -B -m freebie.cli run --city 北京 >> out/weekly.log 2>&1
```

在 DSH harness 里跑，用 `weekly` + `Asia/Shanghai`，prompt 只写三句（**先搜再抓，别让 CLI 自己搜**）：

> 1. 用 `web_search` 搜 `site:mp.weixin.qq.com 北京 免费 音乐会`、`北京 本周末 免费活动汇总`、`北京 免费 展览 市集`，只收 `mp.weixin.qq.com/s` 且带 `chksm=` 的长链。
> 2. 跑 `PYTHONPATH=src python3 -B -m freebie.cli run --city 北京 --urls <上面找到的链接>`。
> 3. 把命令输出原样贴成一条消息；退出码 2 时只回「本周无新增」，**不要补内容、不要改日期**。

城市已备好 `seeds/<城市>.yaml` 的话第 1 步可以省掉，直接 `freebie run --city 北京`——它会自己用那份信源。

## 配置

`cp config.example.yaml config.yaml`（`config.yaml` 已在 .gitignore 里，个人城市/偏好不外传）：

| 键 | 默认 | 说明 |
|---|---|---|
| `city` | 空（必填） | 城市名。CLI 里用 `--city` 给，代码里不写死任何城市 |
| `backend` | auto | `auto` 先试 WeRSS，不可达自动降级 `direct` |
| `werss_url` | http://127.0.0.1:8001 | 可选：we-mp-rss 的地址 |
| `max_items` | 15 | 最多输出几条 |
| `sources` | [] | 固定信源列表；填了就不跑搜索、也不读 seeds |
| `use_seeds` | true | 自动读 `seeds/` 下同城文件的 `channels:` 当信源 |
| `seeds_dir` | "" | 额外的 seeds 目录（默认 `./seeds`、`./seed`、`$FREEBIE_SEEDS`） |
| `filters.max_price` | 80 | 「低价」上限（元） |
| `filters.free_only` | false | 只要免费的 |
| `filters.require_original_price` | false | true 时，低价条目必须带原价才留（防「假的低价」） |
| `filters.lookahead_days` | 10 | 往后看几天 |
| `filters.min_text_len` | 400 | 正文太短的多半是图片海报号，抽不出字段 |

## 可选：接 we-mp-rss

[rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss) 是个常驻服务，扫码登录后能把订阅的公众号转成 RSS/JSON，比裸抓稳。

```bash
docker run -d --name werss -p 8001:8001 -v ./data:/app/data ghcr.io/rachelos/we-mp-rss:latest
freebie run --backend werss
```

不装也完全能用——`direct` 是默认路径。

## 目录

```
src/freebie/
  cli.py        命令入口（run / discover / doctor）
  pipeline.py   候选 → 抓取 → 抽字段 → 过滤 → 去重 → 排序；每个丢弃都记原因
  extract.py    标题/正文/免费/价格/日期/场馆抽取（所有启发式都在这里）
  fetch.py      curl 优先、urllib 兜底；解码
  ranking.py    打分：免费 > 折价 > 临近 > 需预约 > 信息量
  report.py     渲染成一条能直接看的消息（不落盘）
  state.py      state/seen.json：上周推过什么、哪个号最近老失败
  seeds.py      城市 → 信源的查找与 yaml 解析（加城市不改代码）
  sources/      search（多引擎）/ direct（裸抓）/ werss（订阅后端）
seeds/          每个城市一个 yaml：channels（当信源）+ queries + accounts（人工参考）
prompts/        把 JSON 变成人话周报的 LLM prompt
```

## 已知局限（写在这里，免得下次重新踩）

- **公众号只能拿到「有链接的文章」**：单篇文章能抓（需长链含 `chksm`），但**拿不到一个号的完整文章列表**。想要按号盯，接 we-mp-rss。
- **搜索会被风控**：搜狗连续 20~25 次请求后跳 antispider，之后全封；间隔 ≥3s、单轮 ≤10~15 查询。
- **公众号内容不进 `web_fetch`**：会被重定向到 `mp/wappoc_appmsgcaptcha`，必须 curl。
- **活动行/大麦这类平台正文常是前端模板**，抽不到干净摘要时本工具留空，而不是印一行 `{{venueInfo.todoCount}}`。

## 路线图

- v0.2：`seeds/` 接入 we-mp-rss 按号订阅；同一活动的多号转载合并成一条。
- v0.3：`--ics` 导出日历；「开抢/截止」单独提醒（周更和抢票窗口是按小时计的，冲突已知）。
- 不做：全城全品类、App、UGC、票务代理、反爬对抗。

## License

MIT

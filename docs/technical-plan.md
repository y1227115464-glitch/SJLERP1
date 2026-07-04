# 亚马逊订单利润分析工具 - 技术方案

## 目标

构建一个本地运行的简易分析工具，用于处理亚马逊卖家后台导出的订单数据和广告数据。

当前阶段只确定框架，不提前固化利润算法。工具需要先具备稳定的文件导入、字段标准化、数据校验和结果导出能力，后续再补充利润计算规则。

## 产品形态

推荐先做本地 Web 应用，而不是纯命令行脚本。

推荐选择：Streamlit。

原因：

- 业务人员可以通过网页上传文件、预览数据、下载结果，不需要接触代码。
- 分析类工具迭代速度快，适合先把业务口径跑通。
- Streamlit 与 pandas、Excel 导出、图表预览结合成本低。
- 当前阶段不需要维护复杂的前后端工程。

后续升级路径：

- 如果需要多人登录、任务记录、权限管理或定时导入，再拆成 FastAPI 后端 + React 前端。
- 如果数据量明显变大，增加 DuckDB 或 PostgreSQL 作为分析存储层。

## 技术选型

| 模块 | 选择 | 原因 |
| --- | --- | --- |
| 编程语言 | Python 3.12+ | Excel、表格分析、快速建模生态最好 |
| 应用界面 | Streamlit | 快速搭建上传、预览、图表、导出页面 |
| 表格处理 | pandas | 成熟稳定，适合当前订单和广告报表规模 |
| Excel 解析 | openpyxl | 通过 pandas 稳定读取 `.xlsx` 文件 |
| 文本解析 | pandas + charset-normalizer | 处理 `.txt` / `.csv` 类导出文件及编码识别 |
| 数据校验 | pandera | 对 DataFrame 做字段、类型、空值、范围校验 |
| 图表 | Plotly | 可交互展示利润、广告花费、订单趋势 |
| 配置 | YAML + pydantic-settings | 管理站点、币种、字段映射、默认费用配置 |
| 测试 | pytest | 覆盖解析、校验和利润计算规则 |
| 依赖管理 | uv | 安装快，便于锁定依赖版本 |
| 可选存储 | DuckDB | 后续需要本地分析库时再引入 |

## 总体架构

```text
app/
  main.py                 Streamlit 入口
  pages/                  可选的 Streamlit 多页面

src/sjlerp/
  ingestion/
    orders.py             解析 Amazon All Orders / Fulfilment 文件
    ads.py                解析 Amazon 广告 Excel 报告
  schemas/
    orders.py             标准化订单表结构
    ads.py                标准化广告表结构
    profit.py             利润结果表结构
  transform/
    normalize.py          字段映射、日期解析、金额清洗
    matching.py           SKU / ASIN 匹配工具
  analysis/
    profit.py             利润计算策略接口和后续算法
  export/
    excel.py              Excel 结果导出
  config/
    defaults.yaml         站点、费用、字段映射默认配置

tests/
  fixtures/               脱敏样例文件
  test_ingestion_*.py
  test_profit_*.py
```

## 数据流程

```text
输入文件
  -> 文件类型和编码识别
  -> 来源文件解析器
  -> 标准化 DataFrame
  -> 数据结构校验
  -> SKU / ASIN / 日期匹配
  -> 利润计算策略
  -> 结果表
  -> Excel 导出 + Streamlit 预览
```

## 初始中间表设计

### 标准化订单表

预计字段：

- `order_id`
- `purchase_date`
- `sku`
- `asin`
- `product_name`
- `quantity`
- `item_price`
- `item_tax`
- `shipping_price`
- `promotion_discount`
- `amazon_fees`
- `currency`
- `marketplace`

### 标准化广告表

预计字段：

- `date`
- `campaign_name`
- `ad_group_name`
- `sku`
- `asin`
- `impressions`
- `clicks`
- `spend`
- `sales`
- `orders`
- `currency`

### 利润结果表

预计字段：

- `sku`
- `asin`
- `product_name`
- `units_sold`
- `gross_sales`
- `ad_spend`
- `amazon_fees`
- `product_cost`
- `shipping_cost`
- `refund_amount`
- `net_profit`
- `profit_margin`
- `acos`
- `tacos`

这些字段只是框架占位，后续需要根据真实文件列名和利润口径调整。

## 算法扩展点

利润计算定义成可替换策略：

```python
class ProfitCalculator:
    def calculate(self, orders_df, ads_df, cost_df, config) -> pandas.DataFrame:
        ...
```

好处：

- 解析器和界面可以先完成，不阻塞利润公式确认。
- 不同站点、不同会计口径可以使用不同策略。
- 业务规则确认后，可以用测试锁定每条计算规则。

## 第一阶段开发里程碑

1. 创建项目骨架和依赖文件。
2. 基于用户提供的订单 `.txt` 和广告 `.xlsx` 样例文件编写解析器。
3. 将两个输入标准化为稳定的 DataFrame。
4. 增加字段校验和清晰的错误提示。
5. 搭建 Streamlit 上传页面和数据预览。
6. 导出占位版单品分析 Excel，利润列先保留接口。

## 待确认问题

- 商品成本、头程/尾程运费来自第三个输入文件、手动表格，还是配置文件。
- 广告花费按 SKU、ASIN、Campaign 还是其他规则分摊。
- 退款、换货、取消订单、税费如何处理。
- 是否需要币种换算。
- 工具是否只做单次本地分析，还是需要保留历史导入数据。

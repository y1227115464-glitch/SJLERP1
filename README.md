# SJLERP

SJLERP 是一个简易的亚马逊订单与广告数据分析工具。

当前阶段先确定工具框架和技术选型，输入包括：

- 亚马逊后台 Fulfilment / All Orders 导出的订单数据文件
- 亚马逊广告后台导出的广告报告 Excel 文件

目标输出是单品利润情况。具体利润算法、成本口径、广告归因规则、退款处理规则等，后续再单独确定。

## 推荐技术栈

- 运行环境：Python 3.12+
- 应用界面：Streamlit
- 数据处理：pandas + openpyxl
- 数据校验：pandera
- 图表展示：Plotly
- 配置管理：YAML + pydantic-settings
- 自动化测试：pytest
- 依赖管理：uv

这套方案适合先做成本较低、迭代快的本地分析工具；后续如果需要多人使用、历史数据沉淀或定时任务，也可以平滑升级到 FastAPI + React + 数据库。

## 计划流程

1. 上传或选择订单数据文件和广告数据文件。
2. 分别解析两个来源文件，转换成统一的中间表。
3. 校验必需字段、日期范围、金额格式、SKU / ASIN 等关键字段。
4. 按 SKU / ASIN / 日期关联订单、广告和成本数据。
5. 执行利润计算策略。
6. 输出单品利润结果 Excel，并在界面中展示预览和图表。

## 文档

初始框架和技术选型见 [docs/technical-plan.md](docs/technical-plan.md)。

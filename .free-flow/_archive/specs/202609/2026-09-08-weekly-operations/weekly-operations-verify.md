---
doc_type: verify
slug: weekly-operations
status: pass
verified_at: 2026-09-09
---

# W0 交付验收

本次仅验收W0：灵活待办、五类规则、预计发货日和单据事件联动。独立评审通过，七项发现均关闭，详见同目录review记录。W1–W5的FBA快照、补货计算、计划内部分实发等继续按开发计划推进。

| 契约 | 验证方式 | 结果 |
|---|---|---|
| 任意日期采购/发货，无提醒门禁 | test_supply及source联动测试；手动完成待办不改采购/库存 | 通过 |
| 周一09:00、当天未过取当日 | test_task_dates；浏览器采购生成09-14下单事项 | 通过 |
| 已下单补录/实际登记提前完成 | test_completed_tasks_and_manual_overrides；采购create already_ordered与confirm接口 | 通过 |
| 发货与到货分开、缺日不伪造逾期 | source测试与采购详情浏览器核对 | 通过 |
| 改期、手动覆盖、已完成不复活 | test_source_dates_overrides_and_partial_dispatch、completed任务测试 | 通过 |
| 部分发货/取消释放余量/全部实发结束 | 60+40货件测试；原库存并发和收货测试 | 通过 |
| 每日含周末、周五全天、周期继续 | period恢复与模板来源测试；浏览器展示11项自动生成待办 | 通过 |
| 读通知或打开页面不完成、任务不回写业务 | 通知与任务独立API、source测试、浏览器操作 | 通过 |
| 重复提交/多人编辑/重复投递 | TaskOperation、版本冲突测试；PostgreSQL并发创建与投递测试 | 通过 |
| 并发改期旧事件不覆盖新日 | PostgreSQL屏障回归，最终09-25且相关事件均成功处理 | 通过 |
| 规则编辑不与周期生成死锁 | PostgreSQL屏障回归 | 通过 |
| 停机补齐/暂停不补/失败隔离 | period20天追补、pause、失败event退避恢复测试 | 通过 |
| 委派/撤权后任务和汇总通知隔离 | group_notification_reassignment_and_revocation | 通过 |
| 单据深链、切店不显示旧单 | 浏览器从甲店待办进入采购详情，关闭后切乙店，URL变为#purchases且列表为空，不重开甲单 | 通过 |
| 迁移和旧数据保留 | PostgreSQL临时schema升级→check→回退→再升级→check，旧Store保留 | 通过 |
| 无供应商/Amazon/Codex自动写入 | 改动范围反向检查 | 通过 |

## 实际命令结果

- PostgreSQL最终全量：`pytest -q --tb=short`，**71 passed**，0失败。由`SJL_TEST_DATABASE_URL`指向本地实例，fixture为每例建立并清理独立schema。
- SQLite最终全量：同命令，**64 passed、7 skipped**；跳过项均是PostgreSQL专用并发测试，已在上项覆盖。
- 前端：`npm --prefix apps/web run build`及最终构建到临时验收目录，退出码0；`typecheck`退出码0。使用项目Node22执行`npm --prefix apps/web test`，**5 passed**。
- Alembic两次`check`输出 **No new upgrade operations detected.**；升级/回退/再升级和旧档案保留通过。
- `git diff --check`通过。
- 保留原有Starlette/TestClient弃用提示和Vite主包体积提示，无新增依赖。

初次PostgreSQL执行受沙箱本机网络限制，提升执行权限后通过；前端测试最初命中系统旧Node，不支持strip-types，改用项目Node22后通过。迁移验收脚本初次误用了Store不存在的updated_at，修正后完整往返通过；部署脚本最初将健康返回值ok误写为ready，服务已启动，修正验收判断后只读确认所有依赖ok。这些均未被计为成功的产品测试。

## 浏览器与独立调度

在`127.0.0.1:18080`临时验收站点，使用独立PostgreSQL schema、测试账号和单独`app.tasks.worker`进程：

- 新建手动待办、补充全天日期、保存改期、完成后从待处理列表移除；分组计数同步变化。
- 推荐提醒弹窗显示五项约定默认值，保存后五条规则独立可配置。
- 最终版本在不依赖页面调度的情况下自动生成7条日事项、1条周五分析及3条采购事项；周期事项有导入/销售页面链接。
- 采购详情同时展示预计发货与预计到货、登记下单入口及三条关联待办。
- 采购深链后的切店回归通过；页面截图检查未发现遮挡、乱码或错误提示。宽表沿用ERP横向滚动方式。

## 本地部署核对

- 备份：`.local/backups/w0-20260909T091258Z/`，含运行前及停写后数据库dump、前端构建和原提交源码归档，dump目录可读取。
- 已在原实例升级至`48b7a65dc109`，对照停写备份核对店铺、用户、商品、供应商、采购、货件、库存余额与库存流水行数，一致。
- 原Web入口保持，`/health/ready`返回`status/database/redis = ok`，API和scheduler为实际运行进程，scheduler日志无错误。
- 主库规则与待办初始均为0，没有替用户开启模板或为历史单据批量补任务。
- 完整发布结果保存在备份目录`manifest.json`；`.env`和已有业务文件保持原样。

结论：W0可交付。长期使用口径在`docs/task-workbench.md`，核心约束和验证映射在`requirements/tasks/`。

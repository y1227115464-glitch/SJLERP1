# 商品与供应商本轮实现约定

商品、供应商为公司共享基础档案，不从品牌推断店铺授权；当前 CSV 的 ASIN / FNSKU 是来源参考，店铺 Seller SKU 映射留待后续。采购报价独立于售价与核算成本。原 CSV 全字段留存，不把 stock / monthly_sales 当成当前库存或期间销量。

## 接口

统一 `/api/v1`，会话、CSRF、分页 `{items,total}` 和错误沿用现有实现。金额返回十进制字符串，未知金额返回 null。

### 商品

- `GET /products?q=&brand=&is_active=&needs_review=` 分页；`GET /products/{id}` 详情。
- `POST /products`、`PATCH /products/{id}` 新增/修改/停用；不提供硬删除。
- 字段：`id, internal_sku, name, name_zh, brand, category, specifications, material, title, description, asin, fnsku, image_url, image_urls: string[], bullet_points: string[], amazon_url, sale_price: string|null, original_sale_price: string|null, currency, is_active, notes, review_notes: string[], source_data: object|null, source_filename, source_row: number|null, created_at, updated_at`。
- 必填 `internal_sku`（最多120）、`name`（最多500）；其余文本默认空，数组默认空，金额默认 null，currency 默认 USD。name_zh 最多200、brand/category/material最多120、specifications最多2000、description/title/notes最多20000、asin/fnsku最多40、URL最多2000且仅 http/https。source_data/source_filename/source_row 只读；review_notes 可编辑，空数组表示人工核对完成。
- `GET /products/meta`（先注册避免被 /{id} 捕获）返回 `{brands:string[], total, active, needs_review}`。
- `POST /products/import/preview` multipart file + `price_unit=unknown|cents|dollars`。返回 `{token, filename, total, create_count, skip_count, rows:[{row,internal_sku,name,action:'create'|'skip'|'error',review_notes:string[]}], errors:string[], warnings:string[]}`。仅允许本 CSV 格式，最多2000行；预览持久保存解析结果并绑定创建账号；同文件同选项重复导入不创建重复产品。已存在 SKU 跳过且标注，不自动覆盖人工编辑。数据错误时不可确认。
- `POST /products/import/confirm` `{token}` → `{created, skipped, needs_review}`。须重验权限与唯一键，事务提交，幂等；原文件保存在本地私有存储。重复 FNSKU、空格清理、规格矛盾等保留 review_notes；价格单位未知时金额为空且保留来源值。CSV 编码 utf-8-sig / utf-8，JSON 格式字段异常保留原文并提示，不丢行。

### 供应商

- `GET /suppliers?q=&is_active=`、`GET /suppliers/{id}`、`POST /suppliers`、`PATCH /suppliers/{id}`。
- 字段：`id, code, name, contact_name, phone, email, address, payment_terms, notes, is_active, created_at, updated_at`。code 最多50，name 最多200，名称大小写忽略后唯一；其余默认空。code/name必填，其余字段最大长度分别120/80/254/1000/2000/10000。X / x 统一为 X，保留别名说明。

### 采购报价

- `GET /supplier-quotes?supplier_id=&product_id=&q=&review_status=&is_active=&unmatched=`，分页，`unmatched=true` 筛选未关联商品，`GET /supplier-quotes/{id}`。
- `POST /supplier-quotes`、`PATCH /supplier-quotes/{id}`。供应商详情可维护报价；支持无关联商品的报价，不猜测不存在的商品。
- 字段：`id, supplier_id, supplier_name, product_ids:string[], product_names:string[], label, packaging, currency, tax_status:'unknown'|'included'|'excluded'|'mixed', includes_shipping:boolean|null, includes_labeling:boolean|null, labeling_fee:string|null, review_status:'confirmed'|'needs_review', review_notes:string, notes, source_text, source_reference, is_active, tiers:[{min_quantity:number|null, unit_price:string|null, tax_inclusive_price:string|null, unit:string, notes:string}], created_at, updated_at`。
- label最多200，packaging最多500，review_notes/notes/source_text各最多20000，source_reference最多2000，currency默认 CNY。tiers 最多30，每档 min_quantity 正整数或null（未提供起订量，不擅自记作1）；金额≥0且最多4位小数；unit最多40（包/套等），notes最多2000。tiers 至少1项，未知报价可用金额均为空的一档。product_ids去重并验证存在。
- tax_inclusive_price 单独保留原文含税价格，绝不由税率自行推算；明显不一致的未税/含税报价也按来源保留并标记待核对。贴标费保留独立字段，不擅自加到“已含贴标”的单价。所有报价仅供参考，不自动写入正式成本。

## 权限

- products.view：所有现有角色；products.manage：admin/manager/operator（含预览确认）。
- suppliers.view：admin/manager/finance/warehouse；suppliers.manage：admin/manager/finance。
- quotes.view、quotes.manage：admin/manager/finance，同时必须具备 costs.view。其他角色不返回报价金额或原文。
- 公司共享基础档案页明确说明不受顶部店铺/日期筛选影响。
- 变更写审计，日志摘要不含采购金额或报价原文。

## 本轮交付

商品列表/检索/品牌与启停筛选、详情/编辑、新增、CSV预览确认；供应商档案新增编辑、启停、详情及关联报价编辑（多商品、阶梯价格、原始报价、待核对状态）。35条用户商品和全部供货来源导入本地真实库；源码仓库不包含用户原文件或真实报价。

## 售卖店铺与采购候选（2026-09-10）

商品仍为共享档案；新增 `product_stores(store_id, product_id, is_active)` 显式维护售卖范围，不推断 Seller SKU 映射。

- `GET /products?store_id=...&supplier_id=...&is_active=true`：同时提供店铺与供应商时取交集，沿用分页/搜索；供应关系使用启用供应商的启用报价与商品关联，多个报价不重复返回商品。店铺须有权限。
- `GET /products/{id}/stores`：返回 `{items:[{store_id,store_name,store_active,is_active}]}`，仅有权店铺，最多200家。
- `PUT /products/{id}/stores/{store_id}`：请求 `{is_active:true|false}`，需 `products.manage` 和该店铺权限；只更新目标店铺的售卖关系，写审计。
- 新增采购、草稿保存与提交、已提交采购追加商品均校验供货范围；已提交采购的历史行可继续跟进数量，不要求追溯改写历史关系。上下文变更清空前端选择。

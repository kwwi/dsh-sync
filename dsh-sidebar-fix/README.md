# dsh-better-sidebar 依赖版本修复（profile: desktop）

## 诊断结论（只读分析得出）

| 项 | 实际值 |
| --- | --- |
| profile | `/Users/houyuan/.dsh/profiles/desktop` |
| 组合生效处 | `package.json` 的 `dsh.profile.bundles`（`cordis.yml` 与 `cordis.patch.yml` 均为空数组） |
| 部署核心版本 | `@deepseek-ai/*` = `0.1.1-rc.2`，`@deepseek-ai/cordis` = `4.0.1` |
| 问题插件 | `dsh-better-sidebar@0.28.0`，其 peer 契约要求 core `^0.2.1-rc.1` / cordis `^4.0.5` |
| 结果 | 13 条"低于声明下界"风险级依赖不匹配 |

三个补充事实：

1. **不是重复条目，也不是 bundle 顺序问题。** 顶层那份的 patch 行 `better-sidebar` 带 `!!js` 守卫，检测到聚合包已挂载同名插件就自禁用；`@linxin666/dsh-web-ui-all` 又排在它前面，所以只有一份 Node half，没有 duplicate prefix route。
2. **实际在跑的是 0.28.0。** 聚合包虽自带 `dsh-better-sidebar@0.15.2` 并 insert 了 `web-ui-better-sidebar` 行，但 loader 对裸包名按 profile 根解析（`module-resolution.js` 的 `installProfilePackageResolver`），所以该行加载的是顶层 0.28.0。
3. **兼容天花板是 0.17.1。** 0.18.0 起要求 `^0.1.2-rc.1` / cordis `^4.0.2`，仍高于本机；0.17.1 的 16 项 peer 全部 ≥ 声明下界（已逐条核对）。

## 改动内容（仅此一行）

```diff
   "dependencies": {
     "@linxin666/dsh-web-ui-all": "0.3.6",
-    "dsh-better-sidebar": "0.28.0",
+    "dsh-better-sidebar": "0.17.1",
```

随后由 `pnpm install` 按 profile 的 lockfile 重建 `node_modules`。

**不改动**：`dsh.profile.bundles` 顺序、`cordis.patch.yml`、`cordis.yml`、其他插件、harness、核心包。

## 脚本

| 文件 | 用途 |
| --- | --- |
| `apply.sh` / `apply.bat` | 本次修复：建快照 → 改一行 → pnpm install → 校验 |
| `rollback.sh` / `rollback.bat` | 完整撤销 apply，从快照恢复 |
| `tools.cjs` | 两者共用的无依赖小工具（读版本、改写单个依赖、查解析结果） |

### 幂等语义

- **快照只在不存在时创建**；已存在则 `apply` 直接拒绝（exit 3）并提示先 rollback——避免覆盖掉可回滚的原始状态。
- 快照写完后逐字节校验，**校验通过才开始改动**；`SNAPSHOT_OK` 标记最后写入，代表"快照完整"。
- 任何一步失败快照都保留，`rollback` 可把 profile 恢复到 apply 前状态。
- `rollback` 成功后才删除快照，因此**重复 rollback 是安全空操作**（exit 0）。
- 快照内容：`package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`、`cordis.yml`、`cordis.patch.yml`，以及 `node_modules/dsh-better-sidebar`（离线恢复兜底，约 19M）。

### 运行

```bash
cd /Users/houyuan/Documents/mywork/dsh-sidebar-fix
./apply.sh                 # 或 PROFILE=/path TARGET_VERSION=0.15.2 ./apply.sh
```

回滚：

```bash
./rollback.sh              # 追加 --keep-snapshot 可保留快照
```

### 运行后

1. **完全退出并重开 DSH Desktop**，让运行中的进程加载新依赖树。
2. 重跑 profile 诊断，确认 13 条风险消失。
3. 若仍有少量"信息级/未达判定"条目，属于校验器的 prerelease 歧义（`dshmarket/lib/compatibility.js` 的 `classifyPeer` 对这类情况不判为 risk），按约定不处理。

## 请把输出拷回

`apply.sh` 的**完整 stdout/stderr**（含退出码）。若失败，快照会保留，可直接跑 `rollback.sh` 再把输出一并拷回。

# QuantaAlpha Four-Pool Toolkit

用于复现 CSI300、CSI500、CSI1000、CSI2000 四个股票池的多因子组合流程：读取最终因子清单，调用本地 QuantaAlpha 因子表达式与行情数据，生成 point-in-time 池内信号，并把信号交给本地 Quant-Project A 股回测引擎。

本仓库保存的是适配、编排、轻量样例和报告工具，不是独立可运行副本，也不是 QuantaAlpha 或 Quant-Project 的替代品。两个外部项目及研究数据不会上传到本仓库。

## 仓库内容

- `scripts/run_selected_portfolio_qp.py`：四池组合信号、稳健性扫描、目标持仓 CSV 与 QP 回测入口。
- `scripts/qp_backtest_bridge.py`：QuantaAlpha 数据到 Quant-Project 回测表的桥接。
- `generators/`：四个池的薄入口及公共 HTML 报告模块。
- `data/factors_CSI*.txt`：最终因子清单，数量分别为 CSI300=8、CSI500=7、CSI1000=8、CSI2000=5。
- `data/plot_data_CSI*.json`：CSI300/500/1000 的预计算展示样例。

三份 plot JSON 是预计算展示样例，不能单独证明完整回测可以复现。目前样例里的 `main` 与 `proxy` 序列相同，因此只能用于格式、绘图和数据完整性测试，不能当作两套独立实验的证据。

## 外部依赖

需要用户自行准备：

1. 本地 QuantaAlpha 根目录，至少含 `quantaalpha/factors/coder/`、`data/factorlib/`、`data/index_daily/`；行业中性化还需要 `data/industry_map.csv`。
2. 本地 Quant-Project 根目录，至少含 `backtest/ashare/ashare_sse_szse_n_day_factor_backtest.py`。
3. `daily_pv.h5`，包含策略需要的价格、收益、成交量和市值列。

仓库不虚构两个外部项目的远程 URL，也不复制其源码或数据。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

需要 Python 3.11 或更高版本。PyTables 用于 pandas 读取 HDF5。

## 配置

复制 `config.example.toml` 为不会提交的 `config.toml`，填写本机路径：

```powershell
Copy-Item config.example.toml config.toml
```

路径优先级为命令行 > `config.toml` > 默认本地位置。命令行相对路径按当前目录解析，配置文件相对路径按 TOML 所在目录解析。

## 主回测

仓库内因子 TXT 会按 `--pool` 自动选择，也可显式指定：

```powershell
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI300 --factor-list data/factors_CSI300.txt --dedup --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI500 --factor-list data/factors_CSI500.txt --dedup --walk-forward --wf-window 252 --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI1000 --factor-list data/factors_CSI1000.txt --dedup --loo --loo-split 20240101 --output-dir outputs
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI2000 --factor-list data/factors_CSI2000.txt --dedup --slippage-sweep 0,10,20,30,50,100 --output-dir outputs
```

`--factors` 仍可直接传逗号分隔名称；`--sel-dir` 仅用于兼容旧的 HTML 文件名选因子流程。CSI2000 清单中的 `_副本` 后缀会在读取时清理。

`--live` 只根据最近信号日生成目标持仓 CSV，不会连接券商或自动下单：

```powershell
python scripts/run_selected_portfolio_qp.py --config config.toml --pool CSI300 --live --initial-cash 20000000 --output-dir outputs
```

## 报告生成

报告还需要 `report_data_<POOL>.json`、`index_returns.csv`、NAV CSV 和目标持仓 CSV。把这些文件放在 `--input-dir` 指向的目录；缺少任何一个文件都会在写 HTML 前明确失败。

```powershell
python generators/gen_csi300.py --input-dir outputs --output outputs/CSI300_factor_report.html
python generators/gen_csi500_final.py --input-dir outputs --output outputs/CSI500_factor_report.html
python generators/gen_csi1000_report_v2.py --input-dir outputs --output outputs/CSI1000_factor_report.html
python generators/build_html_report.py --input-dir outputs --output outputs/CSI2000_factor_report.html
```

HTML 内的收益、回撤、夏普和超额均从传入净值数据计算；旧脚本中无法由输入验证的固定宣传数字不再输出。

## 输出与版本控制

日志、状态、组合 JSON、NAV、LOO、滑点/调仓扫描、目标持仓和 HTML 默认写入 `outputs/`，该目录被 Git 忽略。HDF5、因子表达式库、调度表、行业映射、指数收益和本地配置同样不会提交。

## 安全说明

为兼容 QuantaAlpha 因子表达式，两个计算路径仍使用 Python `eval`。只允许读取受信任的本地因子表达式库；不要把来自网页、邮件或未知第三方的表达式交给该入口。

## 轻量验证

```powershell
python -m pytest -q
python -m compileall -q scripts generators
git diff --check
```

重型回测需要外部项目和 HDF5。本机缺少这些依赖时应如实标记为“未执行”，不能把轻量测试通过描述成完整策略复跑通过。

## 研究边界

- 默认全样本 ICIR 权重和方向可能包含样本内前视；正式结论优先使用 `--walk-forward`。
- point-in-time 成分过滤、行业中性化和指数基准依赖外部文件质量。
- `--live` 是持仓清单导出，不是交易系统。
- 历史收益、模拟成交和固定滑点不能保证未来可实现收益。

仅用于研究与复现，不构成投资建议。

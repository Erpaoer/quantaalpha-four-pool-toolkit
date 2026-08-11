# QuantaAlpha Four-Pool Toolkit：私有 GitHub 发布设计

日期：2026-08-11
状态：聊天方案已批准，等待书面设计复核

## 1. 目标

将当前四股票池复现材料整理为一个可维护、可审计、不会误上传大数据或凭据的私有 GitHub 仓库：

- 所有者：`Erpaoer`
- 仓库名：`quantaalpha-four-pool-toolkit`
- 可见性：Private
- 默认分支：`main`

仓库用于保存 CSI300、CSI500、CSI1000、CSI2000 四池因子组合回测的适配代码、最终因子清单、轻量示例绘图数据和报告生成工具。它不是 QuantaAlpha 或 Quant-Project 的替代品，也不包含其源码或大型行情数据。

## 2. 已选方案

采用“可维护复现工具包”方案：保留当前研究逻辑和文件角色，修复阻碍迁移与复现的问题，但不尝试把两个外部项目复制进来。

未采用的方案：

1. 原样私有备份：速度最快，但保留硬编码路径、错误报告模板和不可运行目录结构。
2. 完整独立仓库：需要引入 QuantaAlpha、Quant-Project 和大型数据，带来授权、体积和长期维护问题。

## 3. 发布边界

### 纳入版本控制

- 重写后的 `README.md`
- `scripts/` 中的主回测和桥接代码
- `generators/` 中的报告生成代码
- 四份 `data/factors_CSI*.txt`
- 三份轻量 `data/plot_data_CSI*.json`，明确标记为预计算展示样例
- 依赖清单、示例配置、测试和本设计文档

### 不纳入版本控制

- `daily_pv.h5`、其他 HDF5 和原始行情数据
- QuantaAlpha、Quant-Project 的源码副本
- 因子库、指数成分调度表、行业映射和私有研究报告
- 虚拟环境、Python 缓存和测试缓存
- 运行日志、状态文件、NAV、持仓、LOO、滑点扫描、调仓扫描及生成的 HTML
- `.env`、访问令牌、密钥、证书及任何凭据

当前账号下没有发现可直接引用的 QuantaAlpha 或 Quant-Project 仓库，因此 README 将它们描述为用户自行准备的本地外部依赖，不虚构远程 URL。

## 4. 目标结构

```text
quantaalpha-four-pool-toolkit/
├── README.md
├── .gitignore
├── requirements.txt
├── config.example.toml
├── data/
│   ├── factors_CSI300.txt
│   ├── factors_CSI500.txt
│   ├── factors_CSI1000.txt
│   ├── factors_CSI2000.txt
│   └── plot_data_CSI*.json
├── scripts/
│   ├── run_selected_portfolio_qp.py
│   ├── qp_backtest_bridge.py
│   └── toolkit_paths.py
├── generators/
│   ├── report_common.py
│   ├── gen_csi300.py
│   ├── gen_csi500_final.py
│   ├── gen_csi1000_report_v2.py
│   └── build_html_report.py
├── tests/
│   └── test_repository_integrity.py
└── docs/superpowers/specs/
```

不为包装而改名已有入口脚本，避免打断既有命令和研究记录。公共路径解析与报告绘图辅助代码拆出为小模块，减少重复和再次复制错池的风险。

## 5. 路径与配置设计

新增 `config.example.toml`，只记录无凭据的路径键和默认输出目录。命令行参数优先级高于配置文件；没有提供配置时使用相对仓库根目录和常见本地位置。

主回测入口新增或统一以下参数：

- `--qa-root`：QuantaAlpha 根目录
- `--qp-root`：Quant-Project 根目录
- `--data-path`：`daily_pv.h5` 路径
- `--factor-list`：直接读取本仓库因子 TXT
- `--output-dir`：日志、结果和持仓输出目录
- `--config`：可选 TOML 配置文件

仓库根目录按 `scripts/` 的父目录解析，不再把 `scripts/` 错当项目根目录。桥接模块延迟导入外部回测引擎：只有真正运行回测时才验证 `--qp-root` 并导入，保证 `--help`、静态检查和轻量测试不依赖外部项目。

因子 TXT 输入会去空白、去重，并仅对 CSI2000 名称清理结尾 `_副本`，使附带清单可以直接使用。

## 6. 报告生成设计

- 四个现有入口保留，输入目录和输出路径改为命令行参数。
- SVG 绘图、HTML 转义和公共计算迁入 `report_common.py`。
- 池名称、因子数量和因子表从池配置及 `factors_CSI*.txt` 读取，不再复制静态表格。
- 修复 CSI500 报告仍显示“中证1000”和八因子的错误。
- 修复 CSI300 报告使用 CSI1000 因子表的错误。
- 缺少 `report_data`、NAV、指数收益或 CSI2000 目标持仓时，程序给出明确的缺失文件列表并以非零状态退出，不产生半成品报告。
- 报告中的历史绩效结论必须来自输入数据；无法由输入验证的固定宣传数字和容量结论删除或标为研究备注。

## 7. 数据流

```text
因子 TXT / --factors
        + QuantaAlpha 因子表达式库
        + daily_pv.h5
        + point-in-time 成分调度表
        ↓
因子计算 → 中性化 → IC/ICIR → 截面排名 → 组合信号
        ↓
Quant-Project 回测引擎
        ↓
portfolio / NAV / LOO / 压力测试 / 目标持仓
        ↓
报告数据 + 绘图数据 → 自包含 HTML
```

README 会明确区分“本仓库负责的适配与编排”和“外部项目负责的因子解析、数据及撮合逻辑”。

## 8. 错误处理与安全

- 启动时集中检查外部目录、HDF5、因子库、调度表及必要列，并一次性输出可操作的错误信息。
- 禁止在异常时悄悄跳过全部因子后继续生成结果；有效因子不足时明确失败。
- 保留因子表达式 `eval` 机制以兼容 QuantaAlpha，但 README 和代码注释明确只允许可信因子库。
- 发布前扫描常见令牌、私钥、绝对临时路径和超大文件。
- `.gitignore` 精确排除生成物，不使用会误伤示例 JSON 或因子 TXT 的宽泛规则。
- README 加入“仅用于研究与复现，不构成投资建议”的声明。

## 9. 验证策略

轻量验证不要求外部仓库或 1.9 GB 数据：

1. 编译六个 Python 入口及新增模块。
2. 运行 `pytest`，验证四池因子数为 8、7、8、5。
3. 验证 CSI2000 `_副本` 清理及因子去重。
4. 验证三份绘图 JSON 的键、等长序列、日期顺序、唯一性和有限数值。
5. 验证报告池元数据与对应因子清单一致。
6. 验证缺失外部依赖时返回清晰错误，而不是 Python 深层导入异常。
7. 运行 `git diff --check`、敏感信息扫描和待提交文件大小检查。

重型回测不伪装成通过：若本机没有外部项目和 HDF5，交付中明确标记为“未执行，缺少外部依赖”。

## 10. GitHub 发布流程

1. 在本地 `main` 分支提交书面设计。
2. 用户复核设计后，编写实施计划并分步修改。
3. 完成轻量验证和敏感信息检查。
4. 审阅最终暂存范围，确保没有大数据或凭据。
5. 使用已登录的 GitHub CLI 创建：
   `Erpaoer/quantaalpha-four-pool-toolkit --private`
6. 添加 `origin`，推送 `main`，再核对远程可见性为 Private。

GitHub CLI 当前安装于 `C:\Program Files\GitHub CLI\gh.exe`，已登录 `Erpaoer`。执行时使用完整路径，避免当前终端尚未刷新 `PATH` 的影响。

## 11. 完成标准

- 新用户仅阅读 README 即可理解本仓库是什么、依赖什么、哪些结果不能独立验证。
- 所含因子清单可直接作为主脚本输入。
- 代码中不存在 `/sessions/...` 或个人桌面硬编码路径。
- CSI300、CSI500、CSI1000、CSI2000 报告元数据不串池。
- 轻量测试全部通过；重型回测状态如实披露。
- 远程仓库属于 `Erpaoer`、名称正确且保持 Private。
- Git 历史中没有大型原始数据、凭据或外部项目源码。

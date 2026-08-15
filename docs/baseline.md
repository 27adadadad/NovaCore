# 测试基线

- 日期：2026-08-15
- 命令：`python -m pytest tests -q`
- Python：3.13.12
- 结果：3 passed，0 failed，运行时间 0.07s

测试全部离线执行，不访问真实模型或 MCP 服务。pytest 临时目录固定为项目内的 `.pytest-tmp`，以适配受限执行环境。

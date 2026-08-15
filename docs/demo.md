# 演示步骤

## 1. 回归测试

```powershell
python -m pytest tests -q
```

预期：全部测试通过，且不访问网络或真实模型。

## 2. 100 工具延迟发现基准

```powershell
python -c "from benchmarks.tool_discovery import run_fixture; print(run_fixture('benchmarks/fixtures/tools_100.json', 'benchmarks/results/tool_discovery.json'))"
```

预期：100 工具、已发现 3 工具；结果写入 `benchmarks/results/tool_discovery.json`。

## 3. 自动记忆

```powershell
$env:DASHSCOPE_API_KEY = "<your-key>"
$env:AUTO_MEMORY_ENABLED = "true"
python -m novacore -p "本项目所有自动化测试使用 pytest" 
```

任务成功后，自动记忆后台任务会提取稳定项目约束并写入 `.novacore/memory/MEMORY.md`。演示完成后应删除本地 `.novacore/` 数据，避免提交真实对话内容。


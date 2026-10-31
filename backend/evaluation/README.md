# SecondBrain 自动化检索评测说明

本文说明 `evaluation` 目录下各个脚本的用途、执行顺序和结果位置。默认使用 Conda 环境 `knowledgeBase`，不需要修改正式聊天配置。

## 一、先进入后端目录

在 PowerShell 执行：

```powershell
Set-Location D:\desktop\ai知识库\SecondBrain\backend
conda activate knowledgeBase
```

后面的命令都在这个目录执行。

## 二、目录作用

| 路径 | 作用 |
| --- | --- |
| `evaluation_chunks/` | 已导出的父块、子块样本，作为评测原始数据 |
| `generate_test_cases.py` | 根据切分块生成评测问题和标签 |
| `generated_review/` | 生成的题集、拆分和切分质量报告 |
| `run_evaluation.py` | 运行一次检索评测，查看各阶段指标 |
| `tuning/prepare_splits.py` | 按文档拆分训练集、验证集、测试集 |
| `tuning/run_tuning.py` | 使用 Optuna 自动搜索检索参数 |
| `tuning/finalize_test.py` | 用保留测试集评估最终配置 |
| `tuning/` 下的实验目录 | 保存每次自动调参的数据库、配置、指标和图表 |

## 三、每次更新样本后必须执行

当 `evaluation_chunks/` 中的文件有新增、删除或内容修改时，重新生成题集和拆分。

### 1. 生成题集

```powershell
python -m evaluation.generate_test_cases
```

默认输出到 `evaluation/generated_review/`，包括：

```text
test_cases.json
suites/fact.json
suites/heading.json
suites/synthesis.json
test_cases_manifest.json
```

先打开 `evaluation/generated_review/test_cases.json`，检查问题、`document_id`、`relevant_parent_ids` 和 `relevant_chunk_refs` 是否正确。

### 2. 生成训练集、验证集和测试集

```powershell
python -m evaluation.tuning.prepare_splits `
  --input evaluation/generated_review/test_cases.json `
  --output-dir evaluation/generated_review
```

输出位置：

```text
evaluation/generated_review/splits/train.json
evaluation/generated_review/splits/validation.json
evaluation/generated_review/splits/test.json
evaluation/generated_review/split_manifest.json
```

拆分按文档进行，同一文档不会同时出现在不同集合。默认比例是训练集 60%、验证集 20%、测试集 20%。

如果你手动修改了题目或标签，只需要重新执行上面的 `prepare_splits`，不要继续使用旧的 `splits`。

## 四、运行一次普通检索评测

普通评测用于快速观察某一组参数的效果，不会自动搜索参数。
普通评测也需要先启动后端服务；启动方式与“运行自动调参”章节相同。

### 只校验题集标签

```powershell
python -m evaluation.run_evaluation --file evaluation/generated_review/test_cases.json --validate-only
```

### 运行完整题集

```powershell
python -m evaluation.run_evaluation --file evaluation/generated_review/test_cases.json
```

### 只运行某一类问题

```powershell
python -m evaluation.run_evaluation --suite fact
python -m evaluation.run_evaluation --suite heading
python -m evaluation.run_evaluation --suite synthesis
```

注意：`--suite` 默认读取 `evaluation/suites/`。如果要运行刚生成的题集分类文件，使用 `--file`：

```powershell
python -m evaluation.run_evaluation --file evaluation/generated_review/suites/fact.json
```

### 临时覆盖检索参数

```powershell
python -m evaluation.run_evaluation `
  --file evaluation/generated_review/test_cases.json `
  --child-top-k 16 `
  --parent-top-k 4 `
  --rrf-k 60 `
  --reranker-candidates 8
```

约束：`parent_top_k <= reranker_candidates <= child_top_k`。

### 普通评测结果在哪里

每次运行会在 `evaluation/results/resultN/` 生成结果，主要文件如下：

| 文件 | 内容 |
| --- | --- |
| `summary.json` | 本轮总体指标 |
| `results.json` | 每道题的检索结果和命中情况 |
| `question_metrics.csv` | 每道题的 Recall、Precision、MRR、nDCG |
| `run_metadata.json` | 本轮使用的数据和参数 |
| `*.png` / `*.svg` | 指标图表 |

重点看 `summary.json` 和图表中的 Vector、BM25、RRF、Reranker、Context 阶段变化。

## 五、生成切分质量报告

切分质量报告不调用模型，专门检查空块、重复块、块长度、父子块数量和标题覆盖率。

```powershell
python -m evaluation.analyze_chunks `
  --output-dir evaluation/generated_review/chunk_quality
```

主要查看：

```text
evaluation/generated_review/chunk_quality/chunk_quality.json
evaluation/generated_review/chunk_quality/chunk_quality.csv
evaluation/generated_review/chunk_quality/chunk_counts.svg
evaluation/generated_review/chunk_quality/chunk_lengths.svg
evaluation/generated_review/chunk_quality/chunk_issues.svg
```

## 六、运行自动调参

自动调参只搜索以下三个检索参数：

- `child_top_k`
- `rrf_k`
- `reranker_candidates`

搜索范围在 `evaluation/tuning/search_space.json`。默认目标总轮数为 100。

### 1. 启动后端

自动调参需要访问正在运行的后端。另开一个 PowerShell 窗口执行：

```powershell
Set-Location D:\desktop\ai知识库\SecondBrain\backend
conda activate knowledgeBase
python -c "import asyncio,uvicorn; config=uvicorn.Config('main:app',host='127.0.0.1',port=8000,loop='none'); server=uvicorn.Server(config); loop=asyncio.SelectorEventLoop(); asyncio.set_event_loop(loop); loop.run_until_complete(server.serve())"
```

另一个窗口检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/evaluation/snapshot | ConvertTo-Json -Depth 5
```

确认返回的 `bm25_cache_matches_database` 为 `true`。

### 2. 先用 1 轮检查流程

```powershell
python -m evaluation.tuning.run_tuning --trials 1 `
  --experiment-id rag-tuning-20261023-new `
  --dataset evaluation/generated_review/test_cases.json `
  --split-dir evaluation/generated_review/splits `
  --manifest evaluation/generated_review/split_manifest.json
```

确认训练集和验证集都能完成后，再执行正式搜索。

### 3. 正式运行 100 轮

```powershell
python -m evaluation.tuning.run_tuning --trials 100 `
  --experiment-id rag-tuning-20261023-new `
  --dataset evaluation/generated_review/test_cases.json `
  --split-dir evaluation/generated_review/splits `
  --manifest evaluation/generated_review/split_manifest.json
```

程序使用训练集搜索，并使用验证集选出最终配置，不读取测试集。中断后，在题集、拆分、代码和后端检索快照没有变化时，重新执行同一条命令即可续跑。

### 4. 自动调参结果

实验结果保存在：

```text
evaluation/tuning/<实验指纹>/
```

重点查看 `best_config.json`、`validation_results.json` 和 `report.svg`。最终参数仍需经过测试集评估，不能直接修改正式聊天配置。

## 七、运行最终测试集评估

只有 `run_tuning` 完成并生成 `best_config.json` 后，才能使用测试集：

```powershell
python -m evaluation.tuning.finalize_test --fingerprint <实验指纹>
```

结果写入实验目录的 `test_results.json`，并更新 `report.svg`。最终测试完成后实验会锁定。

## 八、建议的日常使用顺序

快速检查：

```powershell
python -m evaluation.run_evaluation --file evaluation/generated_review/test_cases.json --validate-only
python -m evaluation.run_evaluation --suite fact
```

自动调参：

```powershell
python -m evaluation.generate_test_cases
python -m evaluation.tuning.prepare_splits --input evaluation/generated_review/test_cases.json --output-dir evaluation/generated_review
python -m evaluation.tuning.run_tuning --trials 1 --experiment-id rag-tuning-20261023-new --dataset evaluation/generated_review/test_cases.json --split-dir evaluation/generated_review/splits --manifest evaluation/generated_review/split_manifest.json
```

试跑成功后，把 `--trials 1` 改成 `--trials 100`。

## 九、常见错误

- 找不到题集或拆分文件：先运行题集生成和 `prepare_splits`。
- 标签不存在：`evaluation_chunks` 已变化，重新生成题集。
- `bm25_cache_matches_database` 为 `false`：重启后端或刷新检索索引。
- 实验已锁定：创建新的实验输入。
- 参数约束错误：检查 `parent_top_k <= reranker_candidates <= child_top_k`。


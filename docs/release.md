# GitHub Release：审批后交付 CI 产物

发布链路：版本提交推送到codex/pr-review → Offline CI四矩阵成功 → 手动推送版本标签
→ 提取同一SHA的CI安装包 → 查看候选和校验清单 → release环境人工批准 → GitHub Release。
不会部署服务器、发布PyPI、自动合并或因普通push自动发版。

## 维护者操作

1. 在pyproject.toml确定版本。当前0.1.0，标签必须严格对应v0.1.0。
2. 将版本提交推送到codex/pr-review，等待该提交的push CI成功。
3. 维护者明确选择要发布的40位SHA，再创建并推送对应vMAJOR.MINOR.PATCH标签。
   必须在包含release.yml的提交上打标签，不在尚未合并的main上随便打标签。
4. 在Actions的Approved GitHub Release中检查prepare结果；下载release-candidate查看
   wheel、release-manifest.json和SHA256SUMS，确认来源提交和CI运行链接。
5. 点击Review deployments，批准release环境。未批准时不执行publish，不消耗等待中的runner分钟。
6. Release页出现安装包及来源清单。不会覆盖已有Release；失败留下的草稿需要人工检查，不能盲目重跑。

仓库默认分支目前为main，而开发代码在codex/pr-review。本流程用标签push触发，
不依赖workflow_dispatch按钮，也不擅自更改默认分支。本次只配置流程，未创建任何版本标签或Release。

## 审批保护

release环境配置required reviewer为仓库所有者27adadadad，仅v*标签可部署。
单人仓库允许发起人批准自己的部署，但仍须显式点击；这不是双人审批。
删除required reviewer会使环境门禁失效，管理员应保留该保护；流程不能阻止管理员改设置。

prepare作业只读，需要ci.yml的精确SHA、同仓库codex/pr-review的成功push记录，
四个matrix任务全部成功，标签、源码版本和wheel METADATA一致。
复用ubuntu/Python3.13的CI wheel，不重新构建另一版本。CI产物保留7天，过期应重新运行
原提交CI，不退回未验证构建。prepare不执行项目代码，不提取任意ZIP路径。
publish才有contents:write；不checkout仓库、不安装候选代码，先核对候选清单和标签SHA。
Release附wheel、校验清单和含源提交/CI链接的manifest。

此设计信任维护者批准的仓库代码与GitHub Actions平台，不是恶意管理员防护或供应链签名。
Artifact平台digest保留在manifest中用于溯源；另外计算wheel SHA256，不将二者混为一种哈希。
当前支持普通最终三段版本，不支持预发布标签或可执行安装器，不自动更新版本号。
独立的只读prepare_release.py支持--preview-without-tag做准备；这种输出tag_verified=false，
发布作业拒绝它，不能替代真实标签和审批。

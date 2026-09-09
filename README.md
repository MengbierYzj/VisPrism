# vizguide

## 快速启动

```bash
# 后端（FastAPI，127.0.0.1:8000）——不配 LLM key 时慢道为 mock，仍可端到端运行
conda activate vizguide
cd backend && ./scripts/dev.sh

# 前端（vite，localhost:5173，已代理 /api 到后端）
cd frontend && corepack pnpm install && corepack pnpm dev
```

文档索引：研究问题 `doc/研究问题.md` ·后端方案 `doc/后端方案.md` ·
接口契约 `doc/api/接口文档.md`

## 研究问题
本研究从通过对不同机构设计规范进行建模和操作，以支持知识驱动的可视化生成。

**研究对象（What）：Institutional Visualization Knowledge**
  - 定义：机构在长期数据传播实践中沉淀下来的、编纂于其风格指南或设计系统中的可视化设计知识，涵盖图表选择、视觉编码、叙事组织、视觉强调、注释策略与版式规范等，塑造了该机构独特且可辨识的数据表达方式。

**研究视角（Why this lens）**
  - 定义：将设计领域的知识获取并构造为可表示、可执行的知识模型，使其能被系统理解和执行。

**研究方法（How）**
  - 表示：机构设计人格表示方法（Institutional Design Persona）：针对需要统一表示异构、层次混杂的机构可视化设计知识，同时突出不同机构可视化设计知识的独特性的挑战，我们借鉴人格心理学 McAdams 三层次模型（1995/2006），将每份指南统一编码为三层并装配为智能体人格：
    - L1 气质签名 = 恒定规则与令牌（must/never，无条件；Economist 命名色板、BBC 全文字左对齐）；
    - L2 特征适应 = 条件规范（when→then；单序列→BBC 蓝、健康题材→Teal）；
    - L3 叙事认同 = 设计哲学与理由故事（Less is more；Clarity First）。
  - 推理：快慢双通道规范执行（Fast–Slow Norm Execution）：针对设计知识推理过程的强情境依赖，现有方法（纯RAG检索，整个指南模版套用）模板整体套用，无法根据不同情景调用不同设计知识的挑战。我们借鉴双过程理论（Kahneman 2011; Evans & Stanovich 2013），按default-intervened缺省-干预进行推理："慢-快-慢-快"四拍——慢道读图立意（产出语义事实与传播意图）→ 快道规范检测（L1 核违规、L2 程序条件匹配，判不了的列升级清单）→ 慢道溯源裁决（明文担保→采纳；哲学可推导→推导采纳降置信；无担保→驳回不改）→ 快道编译执行与校验（令牌直注 spec 不经 LLM 转录，L1 不变量核验）。
 - 组合与交互：用户跨机构选择性采纳修改，组合设计修改意见生成终稿；对话式微调。

 **应用场景定位**
 设计探索工具Institution-aware Design Exploration System：帮助非专业或专业设计师探索不同机构可能采用哪些设计策略表达同一数据，为设计师提供Design Inspiration。系统不是帮助用户生成一种风格，而是帮助用户比较多种组织化的数据表达方式，理解不同设计知识如何塑造数据传播，并据此形成自己的设计方案。

    - 用系统流程：
    1. 在前端setting panel,用户上传原始图表vega-lite；召唤机构，可以直接选择多个现有已解析好的机构persona agents，也可以上传新的规范让agent解析建模形成具有对应机构的persona agent。
    2. 系统里被选择的每个persona agents开始理解原始图表，以机构自身的persona和快慢通道推理生成对应修改版本展示在前端proposal panel，并且每处改动均有标签说明和具体依据。
    3. 在前端design panel, 用户可以通过选择每个图的修改标签，查看对应依据，并且选择是否要采纳这个修改，如果采纳，可以自动更新在聊天框内。用户可以采纳多个修改策略，然后发送给agent，以修改自己最初的图表。

# RAG 评分报告 — 2026-05-08-batch200-qwen

## 一、元信息

- 时间：2026-05-08T10:09:29+00:00
- 总耗时：281 秒
- 输入：gold=../docs/Public_Test_Set.jsonl / results=./new_result_react_001.legacy.jsonl
- 题数：matched=200 gold_only=0 results_only=0
- 参数：judge_model=aliyun/deepseek-v3.2 strictness=medium top_k=5 concurrency=4

## 二、总分


| 指标 | 值 | 解释 |
|---|---|---|
| **总分** | 87.00% | (答对 + 拒答正确) / 总数 |
| **答对率（作答题）** | 89.58% | 答对 / (答对+答错) |
| **拒答 Recall（覆盖率）** | 90.00% | 应拒题里拒了多少（高 = 不漏 trap）|
| **拒答 Precision（精准率）** | 90.00% | 拒答里真该拒的比例（高 = 不乱拒）|
| **幻觉率 ⚠️** | 10.00% | 应拒题里模型瞎答的比例（= 1 - Recall）|
| **误拒率** | 3.36% | 应答题里模型拒了的比例 |
| **平均置信度** | 0.900 | 仅作答题 |
| Hit@5 严格 | 45.83% | (doc_path, anchor) 完全命中 |
| Hit@5 宽松 | 93.75% | 仅 doc_path 命中（anchor 错也算）|
| 引用精度（严格）| 37.31% | 模型 citations 严格命中比例 |


### 5 个口袋分布


| 口袋 | 题数 |
|---|---|
| 答对 | 129 |
| 答错 | 15 |
| 拒答正确 | 45 |
| 该拒没拒（幻觉⚠️）| 5 |
| 不该拒拒了（漏题）| 5 |
| Judge Failed | 1 |
| **合计** | **200** |


## 三、按 Domain 分组

| Domain | 题数 | 总分 | 答对率 | Hit@5严 | Hit@5宽 | 拒答Recall | 拒答Precision | 误拒率 |
|---|---|---|---|---|---|---|---|---|
| React | 50 | 84.00% | 87.50% | 72.92% | 87.50% | — | 0.00% | 4.00% |
| Kubernetes | 75 | 84.00% | 89.36% | 27.66% | 100.00% | 84.00% | 91.30% | 4.08% |
| Spring Framework | 75 | 92.00% | 91.84% | 36.73% | 93.88% | 96.00% | 96.00% | 2.00% |


## 四、按难度分组

| 难度 | 题数 | 总分 | 答对率 | Hit@5严 | Hit@5宽 | 拒答Recall | 拒答Precision | 误拒率 |
|---|---|---|---|---|---|---|---|---|
| easy | 110 | 86.36% | 89.62% | 45.28% | 91.51% | — | 0.00% | 3.64% |
| medium | 90 | 87.78% | 89.47% | 47.37% | 100.00% | 90.00% | 97.83% | 2.56% |


## 五、Bad Cases（人工 review）

### 5.1 该拒没拒（幻觉 ⚠️）（5 题）


**[k8s_trap_003]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：为 Pod 配置资源请求时，是否必须遵循官方推荐的 `requests` 必须小于或等于 `limits` 的强制策略？
- 标准答案：根据当前文档无法回答该问题，Kubernetes 官方文档中并未规定 `requests` 必须小于或等于 `limits` 的强制策略。虽然这是常见的最佳实践，但系统允许 `requests` 大于 `limits` 的配置（尽管可能造成调度问题）。。
- 模型答案：是的，这是强制策略。Kubernetes 会进行严格校验，若 `requests` 大于 `limits`，Pod 将被判定为无效且无法调度，系统会返回 `must be less than or equal to cpu limit` 的错误。
- 模型引用：docs/kubernetes/规则/limit-range.md#limitrange-and-admission-checks-for-pod

**[k8s_trap_011]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：`kubectl describe` 命令输出的 `Conditions` 部分里，`PodScheduled` 状态为 `True` 是否一定意味着容器已经成功拉取镜像？
- 标准答案：根据当前文档无法回答该问题，`PodScheduled` 条件仅表示 Pod 已被调度到某个节点，与容器镜像拉取（属于 `Initialized` 或 `ContainersReady` 阶段）是两个独立的概念。成功调度不保证镜像拉取成功，这是对 Pod 生命周期状态的混淆。。
- 模型答案：抱歉，我无法从提供的文档中找到答案。Context 中未提及 PodScheduled 条件，也未说明该条件状态与容器镜像拉取成功与否之间的关系，仅涉及 Ready 条件、FailedScheduling 事件及 ImagePullBackOff 状态。

**[k8s_trap_013]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：在定义 CronJob 时，`spec.jobTemplate.spec.template.spec.affinity` 和 `spec.affinity` 这两个字段有什么区别，应该优先使用哪一个？
- 标准答案：根据当前文档无法回答该问题，CronJob 规范 (`spec`) 下根本不存在一个名为 `affinity` 的字段。亲和性配置只能位于 `spec.jobTemplate.spec.template.spec.affinity` 路径下。询问一个不存在的字段与现存字段的区别是无意义的。。
- 模型答案：抱歉，我无法从提供的文档中找到答案。提供的 Context 仅涉及 Pod 和 Deployment 的亲和性配置，未包含任何关于 CronJob 资源结构或 spec.jobTemplate.spec.template.spec.affinity 与 spec.affinity 字段区别的信息。

**[k8s_trap_022]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：Kubernetes 的 `etcd` 数据存储，其一致性模型与 Apache ZooKeeper 的 Zab 协议在应对网络分区时有何根本不同？
- 标准答案：根据当前文档无法回答该问题，这个问题深入比较了两个独立分布式协调系统（etcd使用Raft，ZooKeeper使用Zab）底层共识算法的一致性细节。Kubernetes 文档将 etcd 作为外部依赖，不会详细阐述其内部协议与其他技术的对比。。
- 模型答案：抱歉，我无法从提供的文档中找到答案。Context 中仅提及 etcd 作为 Secret 的底层存储及 ZooKeeper 教程链接，未包含 etcd 一致性模型、Zab 协议或网络分区处理机制的相关信息。

**[spring_trap_024]** domain=Spring Framework difficulty=medium confidence=0.900
- 问题：`@Scheduled` 注解的 `timeUnit` 参数应该如何使用？我想用 `TimeUnit.MINUTES` 来指定 `fixedDelay` 的单位。
- 标准答案：根据当前文档无法回答该问题，`@Scheduled` 注解没有 `timeUnit` 参数。`fixedDelay` 等时间相关属性的单位固定为毫秒，时间单位无法通过参数更改。。
- 模型答案：默认情况下时间单位为毫秒。若要使用分钟，可通过 `@Scheduled` 注解的 `timeUnit` 属性进行配置，例如：`@Scheduled(fixedDelay = <数值>, timeUnit = TimeUnit.MINUTES)`。
- 模型引用：docs/spring/scheduling.adoc#scheduling-annotation-support-scheduled


### 5.2 答错 Top 10（按 confidence 倒序）（10 题）


**[react_005]** domain=React difficulty=easy confidence=0.900
- 问题：Profile组件有没有向Avatar组件传递props？
- 标准答案：没有。
- 模型答案：Profile组件可以向Avatar组件传递props。文档中展示了传递person和size，或使用{...props}语法转发props的示例；但也明确指出在特定代码片段中Profile组件并未向Avatar传递任何props。
- 裁判理由：模型答案包含了与标准答案'没有'相冲突的陈述，标准答案和原文都明确指出在特定代码片段中Profile组件并未向Avatar传递任何props。
- 模型引用：docs/react/passing-props-to-a-component.md#step-1-pass-props-to-the-child-component, docs/react/passing-props-to-a-component.md#passing-props-to-a-component, docs/react/passing-props-to-a-component.md#forwarding-props-with-the-jsx-spread-syntax
- 黄金引用：docs/react/passing-props-to-a-component.md#passing-props-to-a-component

**[react_012]** domain=React difficulty=easy confidence=0.900
- 问题：在哪里可以开始逐页阅读本章？
- 标准答案：前往“使用 Ref 引用值”页面开始逐页阅读本章。
- 模型答案：可前往以下链接开始逐页阅读本章：/learn/your-first-component、/learn/responding-to-events、/learn/referencing-values-with-refs 或 /learn/reacting-to-input-with-state。
- 裁判理由：模型答案包含了错误链接（如/learn/your-first-component），与标准答案及原文出处中指定的唯一链接'/learn/referencing-values-with-refs'相冲突。
- 模型引用：docs/react/describing-the-ui.md#whats-next, docs/react/adding-interactivity.md#whats-next, docs/react/escape-hatches.md#whats-next, docs/react/managing-state.md#whats-next
- 黄金引用：docs/react/escape-hatches.md#what-s-next-whats-next

**[react_013]** domain=React difficulty=medium confidence=0.900
- 问题：在React中，当需要将数据传递多层时，除了使用context，还有哪些更好的做法？
- 标准答案：应该先尝试传递props，如果传递props导致组件层次过深，可以提取组件并使用JSX作为children传递。只有在这些方法都不适用时，才考虑使用context。
- 模型答案：在使用 context 之前，建议先尝试通过 props 传递数据，或者将 JSX 作为 children 传递。
- 裁判理由：模型答案漏掉了标准答案中关键方法'提取组件'，并缺少了'如果传递props导致组件层次过深'和'只有在这些方法都不适用时'这两个重要限制条件。
- 模型引用：docs/react/passing-data-deeply-with-context.md#use-cases-for-context
- 黄金引用：docs/react/passing-data-deeply-with-context.md#before-you-use-context

**[react_015]** domain=React difficulty=medium confidence=0.900
- 问题：将这段HTML代码转换为有效的JSX时，需要注意哪些语法差异？
- 标准答案：转换时需要注意：1. 将 `class` 属性替换为 `className`；2. 修正标签的嵌套顺序，例如 `<b>` 和 `<i>` 标签应正确闭合；3. `<br>` 标签需要写成自闭合形式 `<br />`；4. JSX 表达式外层需要一个根元素包裹。
- 模型答案：转换为JSX时需注意以下语法差异：
1. JSX比HTML更严格，必须正确闭合所有标签（如<br />、<img />）。
2. HTML的class属性需替换为className。
3. 组件不能返回多个根标签，必须将它们包裹在单个共享父元素（如<div>）或空片段<>...</>中。
4. 标签必须严格正确嵌套与闭合。
- 裁判理由：模型答案漏掉了标准答案中的关键点：修正标签嵌套顺序（如`<b>`和`<i>`），且其第四点过于笼统，未能精确对应标准答案的此要求。
- 模型引用：docs/react/writing-markup-with-jsx.md#pro-tip-use-a-jsx-converter, docs/react/writing-markup-with-jsx.md#convert-some-html-to-jsx, docs/react/index.md#writing-markup-with-jsx
- 黄金引用：docs/react/writing-markup-with-jsx.md#convert-some-html-to-jsx

**[react_017]** domain=React difficulty=easy confidence=0.900
- 问题：如果我已经熟悉当前主题，可以阅读哪个章节？
- 标准答案：可以阅读关于“逃生舱口”（Escape Hatches）的章节。
- 模型答案：取决于当前所在章节，可阅读的后续章节分别为 Escape Hatches、Managing State 或 Adding Interactivity。
- 裁判理由：标准答案和原文明确指出是‘Escape Hatches’章节，而模型答案包含不相关的额外选项（Managing State, Adding Interactivity），属于答非所问。
- 模型引用：docs/react/managing-state.md#whats-next, docs/react/adding-interactivity.md#whats-next, docs/react/describing-the-ui.md#whats-next
- 黄金引用：docs/react/managing-state.md#what-s-next-whats-next

**[react_034]** domain=React difficulty=easy confidence=0.900
- 问题：为什么 React 中的代码重复可能会带来维护问题？
- 标准答案：代码重复虽然无害，但会使代码更难维护。例如，如果需要修改 className，就不得不在代码中的多个地方进行更改。
- 模型答案：抱歉，我无法从提供的文档中找到答案。上下文仅列举了避免状态重复的示例，未解释代码重复引发维护问题的具体原因。
- 裁判理由：标准答案明确给出了代码重复导致维护问题的具体原因（如修改className需多处更改），而模型答案声称文档未提供解释，与原文出处冲突。
- 黄金引用：docs/react/conditional-rendering.md#conditionally-including-jsx

**[k8s_017]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：在节点上检查 Pod 的内存 cgroups 时，如何确定 Pod 的标识符？
- 标准答案：首先在特定的节点上确定该 Pod 的标识符。
- 模型答案：在 Pod 被调度到的节点上执行命令 `POD_ID="$(sudo crictl pods --name test-pod -q)"` 即可确定该 Pod 的标识符。
- 裁判理由：模型答案的具体命令方式超出了标准答案/原文仅要求的‘首先在特定节点上确定标识符’的范畴，属于自由发挥。
- 模型引用：docs/kubernetes/调度与驱逐/pod-overhead.md#verify-pod-cgroup-limits
- 黄金引用：docs/kubernetes/调度与驱逐/pod-overhead.md#验证-pod-cgroup-限制-verify-pod-cgroup-limits

**[k8s_028]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：Kubernetes 中如何限制 Admission Webhook 的作用范围以避免不必要的触发？
- 标准答案：建议限制 Webhook 的作用范围，避免处理系统组件和只读请求，将 Webhook 限制到特定的名字空间，并使用匹配条件执行细粒度的请求过滤。
- 模型答案：限制 Admission Webhook 作用范围以避免不必要触发的方法包括：
1. 避免匹配 kube-system 命名空间中的对象，可使用 objectSelector 避免变更关键工作负载。
2. 不要对 kube-node-lease 中的节点租约进行变更，也不要变更 TokenReview 或 SubjectAccessReview 对象（均为只读请求）。
3. 使用 namespaceSelector 将 Webhook 限制到特定命名空间，并排除 Webhook 自身运行的命名空间以防止死锁。
4. 使用匹配条件执行细粒度的请求过滤。
5. 排除 Kubernetes 为响应节点故障等不可避免事件而自动执行的操作。
- 裁判理由：模型答案漏掉了标准答案和原文出处中的关键事实‘避免处理系统组件’（仅提及了部分具体命名空间和对象，但未概括此核心点）。
- 模型引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#webhook-limit-scope, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#request-filtering, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#ha-deployment, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#avoid-self-mutation
- 黄金引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#请求过滤-request-filtering

**[k8s_035]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：如何在Kubernetes中启用Pod的流量整形支持？
- 标准答案：要启用流量整形支持，必须在CNI配置文件中添加`bandwidth`插件，并确保该插件的二进制文件包含在CNI的bin目录中。
- 模型答案：启用Pod流量整形支持需完成以下步骤：1. 将 `bandwidth` 插件添加到CNI配置文件（默认 `/etc/cni/net.d`），并确保该可执行文件位于CNI的bin文件夹内（默认 `/opt/cni/bin`）。2. 在CNI配置中添加 `bandwidth` 插件项，配置 `"type": "bandwidth"` 和 `"capabilities": {"bandwidth": true}`。3. 在Pod中添加 `kubernetes.io/ingress-bandwidth` 和 `kubernetes.io/egress-bandwidth` 注解以设置入站和出站带宽。
- 裁判理由：模型答案添加了标准答案/原文未提及的额外要求（Pod注解设置带宽），这与原文‘必须添加bandwidth插件并确保其二进制文件存在’的核心操作范围不一致。
- 模型引用：docs/kubernetes/计算-存储-网络/network-plugins.md#support-traffic-shaping
- 黄金引用：docs/kubernetes/计算-存储-网络/network-plugins.md#support-traffic-shaping

**[k8s_038]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：Kubernetes 中，名为 foo 的服务公开了一组运行容器 bar 的 Pod，会定义哪些环境变量？
- 标准答案：会定义 FOO_SERVICE_HOST 和 FOO_SERVICE_PORT 两个环境变量，分别表示运行该服务的主机和端口。
- 模型答案：FOO_SERVICE_HOST 和 FOO_SERVICE_PORT
- 裁判理由：模型答案遗漏了标准答案中的关键描述‘分别表示运行该服务的主机和端口’，导致信息不完整。
- 模型引用：docs/kubernetes/容器/container-environment.md#top
- 黄金引用：docs/kubernetes/容器/container-environment.md#集群信息


### 5.3 检索 miss Top 10（答错且 hit@5 严格也没中）（10 题）


**[react_012]** domain=React difficulty=easy confidence=0.900
- 问题：在哪里可以开始逐页阅读本章？
- 标准答案：前往“使用 Ref 引用值”页面开始逐页阅读本章。
- 模型答案：可前往以下链接开始逐页阅读本章：/learn/your-first-component、/learn/responding-to-events、/learn/referencing-values-with-refs 或 /learn/reacting-to-input-with-state。
- 裁判理由：模型答案包含了错误链接（如/learn/your-first-component），与标准答案及原文出处中指定的唯一链接'/learn/referencing-values-with-refs'相冲突。
- 模型引用：docs/react/describing-the-ui.md#whats-next, docs/react/adding-interactivity.md#whats-next, docs/react/escape-hatches.md#whats-next, docs/react/managing-state.md#whats-next
- 黄金引用：docs/react/escape-hatches.md#what-s-next-whats-next

**[react_013]** domain=React difficulty=medium confidence=0.900
- 问题：在React中，当需要将数据传递多层时，除了使用context，还有哪些更好的做法？
- 标准答案：应该先尝试传递props，如果传递props导致组件层次过深，可以提取组件并使用JSX作为children传递。只有在这些方法都不适用时，才考虑使用context。
- 模型答案：在使用 context 之前，建议先尝试通过 props 传递数据，或者将 JSX 作为 children 传递。
- 裁判理由：模型答案漏掉了标准答案中关键方法'提取组件'，并缺少了'如果传递props导致组件层次过深'和'只有在这些方法都不适用时'这两个重要限制条件。
- 模型引用：docs/react/passing-data-deeply-with-context.md#use-cases-for-context
- 黄金引用：docs/react/passing-data-deeply-with-context.md#before-you-use-context

**[react_017]** domain=React difficulty=easy confidence=0.900
- 问题：如果我已经熟悉当前主题，可以阅读哪个章节？
- 标准答案：可以阅读关于“逃生舱口”（Escape Hatches）的章节。
- 模型答案：取决于当前所在章节，可阅读的后续章节分别为 Escape Hatches、Managing State 或 Adding Interactivity。
- 裁判理由：标准答案和原文明确指出是‘Escape Hatches’章节，而模型答案包含不相关的额外选项（Managing State, Adding Interactivity），属于答非所问。
- 模型引用：docs/react/managing-state.md#whats-next, docs/react/adding-interactivity.md#whats-next, docs/react/describing-the-ui.md#whats-next
- 黄金引用：docs/react/managing-state.md#what-s-next-whats-next

**[react_034]** domain=React difficulty=easy confidence=0.900
- 问题：为什么 React 中的代码重复可能会带来维护问题？
- 标准答案：代码重复虽然无害，但会使代码更难维护。例如，如果需要修改 className，就不得不在代码中的多个地方进行更改。
- 模型答案：抱歉，我无法从提供的文档中找到答案。上下文仅列举了避免状态重复的示例，未解释代码重复引发维护问题的具体原因。
- 裁判理由：标准答案明确给出了代码重复导致维护问题的具体原因（如修改className需多处更改），而模型答案声称文档未提供解释，与原文出处冲突。
- 黄金引用：docs/react/conditional-rendering.md#conditionally-including-jsx

**[k8s_017]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：在节点上检查 Pod 的内存 cgroups 时，如何确定 Pod 的标识符？
- 标准答案：首先在特定的节点上确定该 Pod 的标识符。
- 模型答案：在 Pod 被调度到的节点上执行命令 `POD_ID="$(sudo crictl pods --name test-pod -q)"` 即可确定该 Pod 的标识符。
- 裁判理由：模型答案的具体命令方式超出了标准答案/原文仅要求的‘首先在特定节点上确定标识符’的范畴，属于自由发挥。
- 模型引用：docs/kubernetes/调度与驱逐/pod-overhead.md#verify-pod-cgroup-limits
- 黄金引用：docs/kubernetes/调度与驱逐/pod-overhead.md#验证-pod-cgroup-限制-verify-pod-cgroup-limits

**[k8s_028]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：Kubernetes 中如何限制 Admission Webhook 的作用范围以避免不必要的触发？
- 标准答案：建议限制 Webhook 的作用范围，避免处理系统组件和只读请求，将 Webhook 限制到特定的名字空间，并使用匹配条件执行细粒度的请求过滤。
- 模型答案：限制 Admission Webhook 作用范围以避免不必要触发的方法包括：
1. 避免匹配 kube-system 命名空间中的对象，可使用 objectSelector 避免变更关键工作负载。
2. 不要对 kube-node-lease 中的节点租约进行变更，也不要变更 TokenReview 或 SubjectAccessReview 对象（均为只读请求）。
3. 使用 namespaceSelector 将 Webhook 限制到特定命名空间，并排除 Webhook 自身运行的命名空间以防止死锁。
4. 使用匹配条件执行细粒度的请求过滤。
5. 排除 Kubernetes 为响应节点故障等不可避免事件而自动执行的操作。
- 裁判理由：模型答案漏掉了标准答案和原文出处中的关键事实‘避免处理系统组件’（仅提及了部分具体命名空间和对象，但未概括此核心点）。
- 模型引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#webhook-limit-scope, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#request-filtering, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#ha-deployment, docs/kubernetes/集群管理/admission-webhooks-good-practices.md#avoid-self-mutation
- 黄金引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#请求过滤-request-filtering

**[k8s_038]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：Kubernetes 中，名为 foo 的服务公开了一组运行容器 bar 的 Pod，会定义哪些环境变量？
- 标准答案：会定义 FOO_SERVICE_HOST 和 FOO_SERVICE_PORT 两个环境变量，分别表示运行该服务的主机和端口。
- 模型答案：FOO_SERVICE_HOST 和 FOO_SERVICE_PORT
- 裁判理由：模型答案遗漏了标准答案中的关键描述‘分别表示运行该服务的主机和端口’，导致信息不完整。
- 模型引用：docs/kubernetes/容器/container-environment.md#top
- 黄金引用：docs/kubernetes/容器/container-environment.md#集群信息

**[k8s_050]** domain=Kubernetes difficulty=easy confidence=0.900
- 问题：在 Kubernetes 的 Linux 节点上，memory.available 信号的值是从哪里获取的？
- 标准答案：在 Linux 节点上，memory.available 的值来自 CGroupFs，而不是像 free -m 这样的工具。
- 模型答案：在 Linux 节点上，`memory.available` 的值来自 CGroupFs。其计算方式为 `node.status.capacity[memory]` 减去 `node.stats.memory.workingSet`。
- 裁判理由：模型答案在计算方式上引入了标准答案和原文均未提及的 `node.stats.memory.workingSet`，属于添加未授权的关键事实，与仅说明来源为 CGroupFs 的标准答案核心范围不符。
- 模型引用：docs/kubernetes/调度与驱逐/node-pressure-eviction.md#memory-signals, docs/kubernetes/调度与驱逐/node-pressure-eviction.md#eviction-signals
- 黄金引用：docs/kubernetes/调度与驱逐/node-pressure-eviction.md#内存信号-memory-signals

**[spring_037]** domain=Spring Framework difficulty=easy confidence=0.900
- 问题：WebFlux 的 API 通常返回什么类型？
- 标准答案：通常返回 Flux 或 Mono 类型。
- 模型答案：WebFlux 的函数式端点（HandlerFunction）处理 HTTP 请求时，通常返回延迟的 ServerResponse，即 Mono<ServerResponse> 类型。
- 裁判理由：标准答案明确要求回答‘通常返回Flux或Mono类型’，模型答案却限定为‘Mono<ServerResponse>’，漏掉了Flux类型，且偏离了通常情况的核心事实。
- 黄金引用：docs/spring/webflux-reactive-libraries.adoc#reactive-libraries

**[spring_046]** domain=Spring Framework difficulty=easy confidence=0.900
- 问题：在Spring WebFlux中，如何使用ServerRequest访问表单数据？
- 标准答案：可以使用request.formData()方法来访问表单数据，它返回一个Mono<MultiValueMap<String, String>>对象。
- 模型答案：在Java中使用 `request.formData()` 方法，返回 `Mono<MultiValueMap<String, String>>`；在Kotlin中使用 `request.awaitFormData()` 方法。
- 裁判理由：模型答案补充了Kotlin的 `awaitFormData()` 方法，这在标准答案和原文出处中均未提及，属于添加了未经授权的额外信息。
- 模型引用：docs/spring/webflux-functional.adoc#webflux-fn-request
- 黄金引用：docs/spring/webflux-functional.adoc#serverrequest


### 5.4 不该拒拒了（漏题）（5 题）


**[react_036]** domain=React difficulty=easy confidence=0.000
- 问题：React 中，如果没灵感编写组件，可以尝试写什么组件？
- 标准答案：可以写一个 Congratulations 组件，显示 `<h1>Good job!</h1>`。
- 模型答案：抱歉，我无法从提供的文档中找到答案。提供的上下文仅涉及组件嵌套、自定义Hook及Context传递等内容，未提及缺乏灵感时应尝试编写的组件类型或相关建议。
- 黄金引用：docs/react/your-first-component.md#your-own-component

**[react_039]** domain=React difficulty=easy confidence=0.000
- 问题：如果我已经熟悉了 React 描述 UI 的基础知识，文档建议我阅读什么内容？
- 标准答案：建议阅读关于“添加交互性”的内容。
- 模型答案：抱歉，我无法从提供的文档中找到答案。提供的文本片段均被截断，缺失针对已熟悉基础知识用户的后续阅读建议，无法作答。
- 黄金引用：docs/react/describing-the-ui.md#what-s-next-whats-next

**[k8s_026]** domain=Kubernetes difficulty=easy confidence=0.000
- 问题：Kubernetes 中定义了哪几种类型的探针？
- 标准答案：启动探针、存活探针和就绪探针。
- 模型答案：抱歉，我无法从提供的文档中找到答案。Context 仅指出探针共有三种类型，且只明确提及了“就绪探针”，未提供其余两种探针的具体名称，无法完整回答。
- 黄金引用：docs/kubernetes/配置/liveness-readiness-startup-probes.md#top

**[k8s_047]** domain=Kubernetes difficulty=easy confidence=0.000
- 问题：怎么为Kubernetes集群生成证书？
- 标准答案：参阅文档中关于证书的部分。
- 模型答案：抱歉，我无法从提供的文档中找到答案。提供的 Context 中仅包含指向其他文档的参考链接（“要了解如何为集群生成证书，参阅[证书]...”），并未提供具体的证书生成步骤或方法。
- 黄金引用：docs/kubernetes/集群管理/certificates.md#top

**[spring_034]** domain=Spring Framework difficulty=medium confidence=0.000
- 问题：在Spring Framework中，重定向到资源功能主要用于什么场景？
- 标准答案：重定向到资源功能可用于处理单页应用（SPA）中的重定向。
- 模型答案：抱歉，我无法从提供的文档中找到答案。提供的Context中仅包含Spring Framework概述、历史、设计哲学、Resource接口及内置实现、部分配置属性等内容，未提及“重定向到资源”功能及其使用场景。
- 黄金引用：docs/spring/webmvc-functional.adoc#redirecting-to-a-resource


### 5.5 Judge Failed（1 题）


**[k8s_004]** domain=Kubernetes difficulty=medium confidence=0.900
- 问题：在 Kubernetes 中，为什么不应该尝试在准入期间变更镜像 Pod？
- 标准答案：因为所有镜像 Pod 都是不可变的，对它们的更改不会被传播到对应的静态 Pod。
- 模型答案：因为镜像 Pod 是 kubelet 为跟踪静态 Pod 而在 API 服务器中创建的对象，对镜像 Pod 的更改不会被传播到静态 Pod，属于不可更改的对象。
- 模型引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#dont-change-immutable-objects
- 黄金引用：docs/kubernetes/集群管理/admission-webhooks-good-practices.md#不要更改不可变更的对象-dont-change-immutable-objects


## 六、附录

- per_question 全量数据 → 见 .json 报告

/**
 * 推理与引用层 (Reasoning Layer)
 * Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline
 * 
 * 核心要求：
 * 1. 精准注入（转化）- 将检索到的"最小充分信息集合"封装并注入模型
 * 2. 双重溯源（验证）- 同步 + 异步验证机制，确保引用 ID 真实存在
 * 3. 动态治理（清理）- 实时剔除冗余或冲突信息
 * 4. 边界严控（拒答）- 严格限制推理范围，杜绝模型幻觉
 * 5. 效能平衡（分级）- 通过异步校对与分级验证实现最优解
 */

// 导出类型
export * from './types.js';

// 导出组件
export { ContextInjector, createContextInjector } from './context_injector.js';
export { PromptBuilder, createPromptBuilder } from './prompt_builder.js';
export { CitationVerifier, createCitationVerifier } from './citation_verifier.js';
export { RejectionGuard, createRejectionGuard, RejectionReason } from './rejection_guard.js';
export { ContextGovernor, createContextGovernor } from './context_governance.js';
export { ReasoningPipeline, createReasoningPipeline } from './reasoning_pipeline.js';
export { ReasoningWebUI, createReasoningWebUI } from './webui.js';

// 导出主要类
export { ReasoningPipeline as ReasoningEngine } from './reasoning_pipeline.js';

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NLU 模型调用测试脚本
用于测试指代消解、查询改写、完整性检查三个模型的功能
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from category_classifier.nlu.pipeline import NLUPipeline


async def test_pronoun_resolution():
    """测试指代消解"""
    print("\n" + "="*60)
    print("🧪 测试指代消解 (RexUniNLU)")
    print("="*60)
    
    pipeline = NLUPipeline()
    
    # 测试用例 1：包含指代词
    question1 = "它多少钱？"
    history1 = [
        {"user_message": "我想了解 iPhone 15 的价格", "assistant_message": "iPhone 15 售价 5999 元起。"},
        {"user_message": "那 iPhone 15 Pro 呢？", "assistant_message": "iPhone 15 Pro 售价 7999 元起。"}
    ]
    
    print(f"\n原始问题：{question1}")
    print(f"上下文：{len(history1)} 轮对话")
    
    resolved, replaced = await pipeline.resolve_pronoun(question1, history1)
    
    print(f"替换后：{resolved}")
    print(f"是否替换：{replaced}")
    
    # 测试用例 2：不包含指代词
    question2 = "iPhone 15 多少钱？"
    resolved2, replaced2 = await pipeline.resolve_pronoun(question2, [])
    
    print(f"\n原始问题：{question2}")
    print(f"替换后：{resolved2}")
    print(f"是否替换：{replaced2}")
    
    print("\n✅ 指代消解测试完成")


async def test_query_rewriting():
    """测试查询改写"""
    print("\n" + "="*60)
    print("🧪 测试查询改写 (SlimPLM)")
    print("="*60)
    
    pipeline = NLUPipeline()
    
    # 测试用例 1：简单改写
    question1 = "请问怎么申请年假？"
    
    print(f"\n原始问题：{question1}")
    
    rewritten = await pipeline.rewrite_query(question1)
    
    print(f"改写后：{rewritten}")
    
    # 测试用例 2：复杂改写
    question2 = "我想了解一下员工福利是什么"
    
    print(f"\n原始问题：{question2}")
    
    rewritten2 = await pipeline.rewrite_query(question2)
    
    print(f"改写后：{rewritten2}")
    
    print("\n✅ 查询改写测试完成")


async def test_completeness_check():
    """测试完整性检查"""
    print("\n" + "="*60)
    print("🧪 测试完整性检查 (TurnSense)")
    print("="*60)
    
    pipeline = NLUPipeline()
    
    # 测试用例 1：完整问题
    question1 = "如何申请员工年假？"
    
    print(f"\n问题：{question1}")
    
    is_complete, message = await pipeline.check_completeness(question1)
    
    print(f"是否完整：{is_complete}")
    print(f"提示信息：{message}")
    
    # 测试用例 2：不完整问题
    question2 = "申请"
    
    print(f"\n问题：{question2}")
    
    is_complete2, message2 = await pipeline.check_completeness(question2)
    
    print(f"是否完整：{is_complete2}")
    print(f"提示信息：{message2}")
    
    # 测试用例 3：过短问题
    question3 = "怎么弄？"
    
    print(f"\n问题：{question3}")
    
    is_complete3, message3 = await pipeline.check_completeness(question3)
    
    print(f"是否完整：{is_complete3}")
    print(f"提示信息：{message3}")
    
    print("\n✅ 完整性检查测试完成")


async def test_full_pipeline():
    """测试完整 NLU 流程"""
    print("\n" + "="*60)
    print("🧪 测试完整 NLU 流程")
    print("="*60)
    
    pipeline = NLUPipeline()
    
    # 测试用例：包含指代词的完整问题
    question = "它多少钱？"
    session_id = "test-session-123"
    
    history = [
        {"user_message": "我想了解 iPhone 15 的价格", "assistant_message": "iPhone 15 售价 5999 元起。"}
    ]
    
    print(f"\n原始问题：{question}")
    print(f"Session ID: {session_id}")
    
    # 手动执行完整流程
    # 1. 指代判断
    has_pron = pipeline.has_pronoun(question)
    print(f"\n1️⃣ 指代判断：包含指代词 = {has_pron}")
    
    # 2. 指代替换
    if has_pron and history:
        resolved, replaced = await pipeline.resolve_pronoun(question, history)
        print(f"2️⃣ 指代替换：{question} -> {resolved} (成功={replaced})")
        question = resolved
    
    # 3. 查询改写
    rewritten = await pipeline.rewrite_query(question)
    print(f"3️⃣ 查询改写：{question} -> {rewritten}")
    
    # 4. 完整性检查
    is_complete, message = await pipeline.check_completeness(rewritten)
    print(f"4️⃣ 完整性检查：完整={is_complete}, 消息={message}")
    
    print("\n✅ 完整 NLU 流程测试完成")


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("🚀 NLU 模型调用测试")
    print("="*60)
    
    # 检查模型配置
    pipeline = NLUPipeline()
    
    print("\n📋 模型配置:")
    print(f"  RexUniNLU (指代消解):")
    print(f"    - 本地模式：{pipeline.use_local_rexnunlu}")
    print(f"    - API 模式：{pipeline.use_api_rexnunlu}")
    print(f"    - 模型路径：{pipeline.rexnunlu_model_path or '未配置'}")
    print(f"    - API URL: {pipeline.rexnunlu_api_url or '未配置'}")
    
    print(f"\n  SlimPLM (查询改写):")
    print(f"    - 本地模式：{pipeline.use_local_slimplm}")
    print(f"    - API 模式：{pipeline.use_api_slimplm}")
    print(f"    - 模型路径：{pipeline.slimplm_model_path or '未配置'}")
    print(f"    - API URL: {pipeline.slimplm_api_url or '未配置'}")
    
    print(f"\n  TurnSense (完整性检查):")
    print(f"    - 本地模式：{pipeline.use_local_turnsense}")
    print(f"    - API 模式：{pipeline.use_api_turnsense}")
    print(f"    - 模型路径：{pipeline.turnsense_model_path or '未配置'}")
    print(f"    - API URL: {pipeline.turnsense_api_url or '未配置'}")
    
    print(f"\n🖥️  计算设备：{pipeline.device}")
    
    # 执行测试
    await test_pronoun_resolution()
    await test_query_rewriting()
    await test_completeness_check()
    await test_full_pipeline()
    
    print("\n" + "="*60)
    print("🎉 所有测试完成！")
    print("="*60)
    
    print("\n💡 提示:")
    if not (pipeline.use_local_rexnunlu or pipeline.use_api_rexnunlu):
        print("  ⚠️  RexUniNLU 模型未配置，使用规则降级方案")
    if not (pipeline.use_local_slimplm or pipeline.use_api_slimplm):
        print("  ⚠️  SlimPLM 模型未配置，使用规则降级方案")
    if not (pipeline.use_local_turnsense or pipeline.use_api_turnsense):
        print("  ⚠️  TurnSense 模型未配置，使用规则降级方案")
    
    print("\n📚 查看部署指南：NLU_MODEL_DEPLOY.md")


if __name__ == "__main__":
    asyncio.run(main())

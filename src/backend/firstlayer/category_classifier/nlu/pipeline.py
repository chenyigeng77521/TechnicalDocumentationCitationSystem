# -*- coding: utf-8 -*-
"""
NLU 处理流水线 - 指代消解 + 查询改写 + 完整性检查
"""

import re
import os
import json
import httpx
import logging
import torch
from typing import Dict, List, Optional, Tuple
from config import Config
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM

logger = logging.getLogger("nlu_pipeline")


class NLUPipeline:
    """NLU 处理流水线"""
    
    def __init__(self):
        self.context_memory_url = Config.CONTEXT_MEMORY_URL
        self.retrieval_url = Config.RETRIEVAL_URL
        self.timeout = Config.HTTP_TIMEOUT
        
        # NLU 模型配置（本地部署）
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'models')
        self.rexnunlu_model_path = os.path.join(base_path, 'qwen2.5-0.5b')  # 使用 Qwen2.5-0.5B 做指代消解 + 查询改写
        self.slimplm_model_path = ""  # 不单独使用，与 RexUniNLU 合并
        self.turnsense_model_path = os.path.join(base_path, 'chinese-roberta-wwm-ext')  # 完整性检查
        
        # 检查是否启用模型（本地模式）
        self.use_local_rexnunlu = bool(self.rexnunlu_model_path and os.path.exists(self.rexnunlu_model_path))
        self.use_local_slimplm = False  # 不单独使用
        self.use_local_turnsense = bool(self.turnsense_model_path and os.path.exists(self.turnsense_model_path))
        
        # 使用 Qwen2.5-0.5B 的标志（用于指代消解和查询改写）
        self.use_qwen25 = self.use_local_rexnunlu
        
        # 检查是否启用 API 模式
        self.rexnunlu_api_url = os.getenv('REXUNINLU_API_URL', '')
        self.slimplm_api_url = os.getenv('SLIMPLM_API_URL', '')
        self.turnsense_api_url = os.getenv('TURNSENSE_API_URL', '')
        self.use_api_rexnunlu = bool(self.rexnunlu_api_url)
        self.use_api_slimplm = bool(self.slimplm_api_url)
        self.use_api_turnsense = bool(self.turnsense_api_url)
        
        # 模型实例（懒加载）
        self.rexnunlu_tokenizer = None
        self.rexnunlu_model = None
        self.slimplm_tokenizer = None
        self.slimplm_model = None
        self.turnsense_tokenizer = None
        self.turnsense_model = None
        
        # 设备配置（CPU 优化）
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # CPU 优化配置（从环境变量读取）
        self.use_cpu_optimization = os.getenv('NLU_CPU_OPTIMIZATION', 'true').lower() == 'true'
        self.use_4bit_quantization = os.getenv('NLU_4BIT_QUANTIZATION', 'true').lower() == 'true'
        
        if self.device.type == "cpu":
            logger.info("🖥️  检测到 CPU 环境，启用 CPU 优化模式")
            if self.use_4bit_quantization:
                logger.info("⚡ 启用 4bit 量化（减少内存占用）")
        
        # 指代词规则（中文常见指代词）
        self.pronouns = [
            r'它', r'它们', r'这个', r'那', r'那个', r'这些', r'那些',
            r'此', r'该', r'其', r'上述', r'前述', r'上文', r'下面',
            r'他', r'她', r'他们', r'她们', r'自己', r'本人', r'该问题',
            r'该文档', r'该文件', r'这个功能', r'那个功能', r'此功能'
        ]
        self.pronoun_pattern = re.compile('|'.join(self.pronouns))
        
        # 指代词规则（中文常见指代词）
        self.pronouns = [
            r'它', r'它们', r'这个', r'那', r'那个', r'这些', r'那些',
            r'此', r'该', r'其', r'上述', r'前述', r'上文', r'下面',
            r'他', r'她', r'他们', r'她们', r'自己', r'本人', r'该问题',
            r'该文档', r'该文件', r'这个功能', r'那个功能', r'此功能'
        ]
        self.pronoun_pattern = re.compile('|'.join(self.pronouns))
        
    def has_pronoun(self, question: str) -> bool:
        """检查问题是否包含指代词"""
        return bool(self.pronoun_pattern.search(question))
    
    async def get_context_history(self, session_id: str, turns: int = 2) -> List[Dict]:
        """从上下文记忆服务获取历史对话"""
        try:
            url = f"{self.context_memory_url}/api/context/get-latest-conversations/{session_id}"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        conversations = data.get("conversations", [])
                        # 只取最近 turns 轮
                        return conversations[-turns:] if conversations else []
            return []
        except Exception as e:
            logger.error(f"获取上下文历史失败：{e}")
            return []
    
    def _load_rexnunlu_model(self):
        """加载 RexUniNLU 模型（本地模式，支持 CPU 优化）"""
        if self.rexnunlu_tokenizer is not None:
            return True
            
        try:
            if not self.use_local_rexnunlu:
                return False
                
            logger.info(f"🔄 正在加载 RexUniNLU 模型：{self.rexnunlu_model_path}")
            
            # 加载 tokenizer
            self.rexnunlu_tokenizer = AutoTokenizer.from_pretrained(
                self.rexnunlu_model_path,
                trust_remote_code=True
            )
            
            # CPU 优化：4bit 量化
            if self.use_cpu_optimization and self.use_4bit_quantization:
                try:
                    from transformers import BitsAndBytesConfig
                    
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float32,  # CPU 使用 float32
                        bnb_4bit_quant_type="nf4"
                    )
                    
                    self.rexnunlu_model = AutoModelForCausalLM.from_pretrained(
                        self.rexnunlu_model_path,
                        quantization_config=quantization_config,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
                    logger.info("✅ RexUniNLU 模型加载完成（4bit 量化）")
                    
                except ImportError:
                    logger.warning("⚠️  bitsandbytes 未安装，使用普通模式")
                    self.rexnunlu_model = AutoModelForCausalLM.from_pretrained(
                        self.rexnunlu_model_path,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
            else:
                # 普通模式
                self.rexnunlu_model = AutoModelForCausalLM.from_pretrained(
                    self.rexnunlu_model_path,
                    trust_remote_code=True,
                    device_map="cpu"
                )
            
            logger.info(f"✅ RexUniNLU 模型加载完成！设备：{self.device}")
            return True
            
        except Exception as e:
            logger.error(f"❌ RexUniNLU 模型加载失败：{str(e)}")
            self.use_local_rexnunlu = False
            return False
    
    async def resolve_pronoun(self, question: str, history: List[Dict]) -> Tuple[str, bool]:
        """
        指代替换 - 支持三种模式：
        1. API 模式：调用远程 API
        2. 本地模式：加载本地模型
        3. 规则模式：使用简单规则（降级方案）
        
        返回：(替换后的问题，是否成功替换)
        """
        if not self.has_pronoun(question):
            return question, False
        
        if not history:
            return question, False
        
        # 拼接上下文
        context = " ".join([f"用户：{conv.get('user_message', '')}" for conv in history[-2:]])
        
        # 1️⃣ 优先尝试 API 模式
        if self.use_api_rexnunlu:
            try:
                result = await self._call_rexnunlu_api(question, context)
                if result and result.get("success"):
                    logger.info(f"✅ RexUniNLU API 指代替换成功")
                    return result.get("resolved_question", question), True
            except Exception as e:
                logger.error(f"❌ RexUniNLU API 调用失败：{e}")
        
        # 2️⃣ 尝试本地模型
        if self.use_local_rexnunlu or self._load_rexnunlu_model():
            try:
                result = self._call_rexnunlu_model(question, context)
                if result and result != question:
                    logger.info(f"✅ RexUniNLU 模型指代替换成功")
                    return result, True
            except Exception as e:
                logger.error(f"❌ RexUniNLU 模型推理失败：{e}")
        
        # 3️⃣ 降级到规则模式
        logger.warning("⚠️  使用规则模式进行指代替换（降级方案）")
        return self._resolve_pronoun_by_rule(question, history)
    
    async def _call_rexnunlu_api(self, question: str, context: str) -> Optional[Dict]:
        """调用 RexUniNLU API"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.rexnunlu_api_url,
                    json={
                        "question": question,
                        "context": context
                    }
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"RexUniNLU API 调用失败：{e}")
        return None
    
    def _call_rexnunlu_model(self, question: str, context: str) -> str:
        """使用 Qwen2.5-0.5B 进行指代消解和查询改写"""
        if not self.rexnunlu_tokenizer or not self.rexnunlu_model:
            return question
        
        # 构造提示词（Qwen2.5 的对话格式）
        prompt = f"""<|im_start|>system
你是一位 NLU 专家，负责指代消解和查询改写。
任务：
1. 如果问题包含指代词（它、这个、那个等），请用上下文中的实体替换
2. 优化查询，使其更清晰、更适合检索

<|im_end|>
<|im_start|>user
上下文：{context}
当前问题：{question}

请直接输出优化后的问题，不要有其他内容。<|im_end|>
<|im_start|>assistant
"""
        
        inputs = self.rexnunlu_tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=512
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.rexnunlu_model.generate(
                **inputs,
                max_length=256,
                num_beams=3,
                temperature=0.7,
                do_sample=True
            )
        
        # 提取回答部分
        full_response = self.rexnunlu_tokenizer.decode(outputs[0], skip_special_tokens=True)
        # 提取 assistant 的回答
        if "<|im_start|>assistant" in full_response:
            response = full_response.split("<|im_start|>assistant")[-1].strip()
        else:
            response = full_response.strip()
        
        return response
    
    def _resolve_pronoun_by_rule(self, question: str, history: List[Dict]) -> Tuple[str, bool]:
        """使用规则进行指代替换（降级方案）"""
        for conv in reversed(history):
            user_msg = conv.get("user_message", "")
            entities = self._extract_entities(user_msg)
            if entities:
                resolved = question
                replaced = False
                for entity in entities[:2]:
                    for pronoun in self.pronouns:
                        if pronoun in question and not replaced:
                            resolved = resolved.replace(pronoun, entity, 1)
                            replaced = True
                            break
                if replaced:
                    return resolved, True
        
        return question, False
    
    def _extract_entities(self, text: str) -> List[str]:
        """从文本中提取实体（简单规则，降级方案使用）"""
        entities = []
        patterns = [
            r'[A-Z]{2,}',
            r'[\u4e00-\u9fff]{2,6}',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches)
        return list(set(entities))[:5]
    
    def _load_slimplm_model(self):
        """加载 SlimPLM 查询改写模型（本地模式，支持 CPU 优化）"""
        if self.slimplm_tokenizer is not None:
            return True
            
        try:
            if not self.use_local_slimplm:
                return False
                
            logger.info(f"🔄 正在加载 SlimPLM 模型：{self.slimplm_model_path}")
            
            self.slimplm_tokenizer = AutoTokenizer.from_pretrained(
                self.slimplm_model_path,
                trust_remote_code=True
            )
            
            # CPU 优化：4bit 量化
            if self.use_cpu_optimization and self.use_4bit_quantization:
                try:
                    from transformers import BitsAndBytesConfig
                    
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float32,
                        bnb_4bit_quant_type="nf4"
                    )
                    
                    self.slimplm_model = AutoModelForCausalLM.from_pretrained(
                        self.slimplm_model_path,
                        quantization_config=quantization_config,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
                    logger.info("✅ SlimPLM 模型加载完成（4bit 量化）")
                    
                except ImportError:
                    logger.warning("⚠️  bitsandbytes 未安装，使用普通模式")
                    self.slimplm_model = AutoModelForCausalLM.from_pretrained(
                        self.slimplm_model_path,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
            else:
                self.slimplm_model = AutoModelForCausalLM.from_pretrained(
                    self.slimplm_model_path,
                    trust_remote_code=True,
                    device_map="cpu"
                )
            
            logger.info(f"✅ SlimPLM 模型加载完成！设备：{self.device}")
            return True
            
        except Exception as e:
            logger.error(f"❌ SlimPLM 模型加载失败：{str(e)}")
            self.use_local_slimplm = False
            return False
    
    def _load_turnsense_model(self):
        """加载 TurnSense 完整性检查模型（本地模式，支持 CPU 优化）"""
        if self.turnsense_tokenizer is not None:
            return True
            
        try:
            if not self.use_local_turnsense:
                return False
                
            logger.info(f"🔄 正在加载 TurnSense 模型：{self.turnsense_model_path}")
            
            self.turnsense_tokenizer = AutoTokenizer.from_pretrained(
                self.turnsense_model_path,
                trust_remote_code=True
            )
            
            # CPU 优化：4bit 量化
            if self.use_cpu_optimization and self.use_4bit_quantization:
                try:
                    from transformers import BitsAndBytesConfig
                    
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float32,
                        bnb_4bit_quant_type="nf4"
                    )
                    
                    self.turnsense_model = AutoModelForCausalLM.from_pretrained(
                        self.turnsense_model_path,
                        quantization_config=quantization_config,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
                    logger.info("✅ TurnSense 模型加载完成（4bit 量化）")
                    
                except ImportError:
                    logger.warning("⚠️  bitsandbytes 未安装，使用普通模式")
                    self.turnsense_model = AutoModelForCausalLM.from_pretrained(
                        self.turnsense_model_path,
                        trust_remote_code=True,
                        device_map="cpu"
                    )
            else:
                self.turnsense_model = AutoModelForCausalLM.from_pretrained(
                    self.turnsense_model_path,
                    trust_remote_code=True,
                    device_map="cpu"
                )
            
            logger.info(f"✅ TurnSense 模型加载完成！设备：{self.device}")
            return True
            
        except Exception as e:
            logger.error(f"❌ TurnSense 模型加载失败：{str(e)}")
            self.use_local_turnsense = False
            return False
    
    async def rewrite_query(self, question: str) -> str:
        """
        查询改写 - 支持三种模式：
        1. API 模式：调用远程 API
        2. 本地模式：加载本地模型
        3. 规则模式：使用简单规则（降级方案）
        """
        # 1️⃣ 优先尝试 API 模式
        if self.use_api_slimplm:
            try:
                result = await self._call_slimplm_api(question)
                if result and result.get("success"):
                    logger.info(f"✅ SlimPLM API 查询改写成功")
                    return result.get("rewritten_question", question)
            except Exception as e:
                logger.error(f"❌ SlimPLM API 调用失败：{e}")
        
        # 2️⃣ 尝试本地模型
        if self.use_local_slimplm or self._load_slimplm_model():
            try:
                result = self._call_slimplm_model(question)
                if result and result != question:
                    logger.info(f"✅ SlimPLM 模型查询改写成功")
                    return result
            except Exception as e:
                logger.error(f"❌ SlimPLM 模型推理失败：{e}")
        
        # 3️⃣ 降级到规则模式
        logger.warning("⚠️  使用规则模式进行查询改写（降级方案）")
        return self._rewrite_query_by_rule(question)
    
    async def _call_slimplm_api(self, question: str) -> Optional[Dict]:
        """调用 SlimPLM API"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.slimplm_api_url,
                    json={"question": question}
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"SlimPLM API 调用失败：{e}")
        return None
    
    def _call_slimplm_model(self, question: str) -> str:
        """使用本地 SlimPLM 模型进行查询改写"""
        if not self.slimplm_tokenizer or not self.slimplm_model:
            return question
        
        # 构造输入（根据 SlimPLM 的输入格式调整）
        input_text = f"query rewriting: {question}"
        
        inputs = self.slimplm_tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.slimplm_model.generate(
                **inputs,
                max_length=128,
                num_beams=5,
                early_stopping=True
            )
        
        rewritten = self.slimplm_tokenizer.decode(outputs[0], skip_special_tokens=True)
        return rewritten
    
    def _rewrite_query_by_rule(self, question: str) -> str:
        """使用规则进行查询改写（降级方案）"""
        rewritten = question
        # 移除冗余词
        rewritten = re.sub(r'请问', '', rewritten)
        rewritten = re.sub(r'怎么', '如何', rewritten)
        rewritten = re.sub(r'是什么', '', rewritten)
        return rewritten
    
    async def check_completeness(self, question: str) -> Tuple[bool, str]:
        """
        完整性检查 - 支持三种模式
        返回：(是否完整，提示信息)
        """
        # 第一层：规则快速过滤
        is_complete, message = self._rule_based_check(question)
        if not is_complete:
            return False, message
        
        # 第二层：尝试模型检查
        # 1️⃣ 优先尝试 API 模式
        if self.use_api_turnsense:
            try:
                result = await self._call_turnsense_api(question)
                if result and result.get("success") is not None:
                    logger.info(f"✅ TurnSense API 完整性检查完成")
                    return result.get("is_complete", True), result.get("message", "通过 API 检查")
            except Exception as e:
                logger.error(f"❌ TurnSense API 调用失败：{e}")
        
        # 2️⃣ 尝试本地模型
        if self.use_local_turnsense or self._load_turnsense_model():
            try:
                is_complete, message = self._call_turnsense_model(question)
                if not is_complete:
                    return False, message
                logger.info(f"✅ TurnSense 模型完整性检查通过")
                return True, "通过模型检查"
            except Exception as e:
                logger.error(f"❌ TurnSense 模型推理失败：{e}")
        
        # 3️⃣ 降级到规则模式
        logger.warning("⚠️  使用规则模式进行完整性检查（降级方案）")
        return True, "通过规则检查"
    
    async def _call_turnsense_api(self, question: str) -> Optional[Dict]:
        """调用 TurnSense API"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.turnsense_api_url,
                    json={"question": question}
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"TurnSense API 调用失败：{e}")
        return None
    
    def _call_turnsense_model(self, question: str) -> Tuple[bool, str]:
        """使用 chinese-roberta-wwm-ext 进行完整性检查"""
        if not self.turnsense_tokenizer or not self.turnsense_model:
            return True, "模型不可用"
        
        # 构造输入
        input_text = f"问题完整性检查：{question}"
        
        inputs = self.turnsense_tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.turnsense_model(**inputs)
            probabilities = torch.softmax(outputs.logits, dim=-1)
            # 类别 0：完整，类别 1：不完整
            complete_prob = probabilities[0][0].item()
        
        # 阈值判断（0.5）
        if complete_prob < 0.5:
            return False, "问题不完整，请提供更多上下文信息"
        
        return True, f"通过模型检查（完整性得分：{complete_prob:.2f}）"
    
    def _rule_based_check(self, question: str) -> Tuple[bool, str]:
        """规则快速过滤"""
        question = question.strip()
        
        # 空检查
        if not question:
            return False, "问题不能为空"
        
        # 长度检查
        if len(question) < 2:
            return False, "问题太短，请提供更详细的描述"
        
        # 格式错误检查
        if question.count('?') > 3:
            return False, "问题格式异常"
        
        # 乱码检查
        if re.search(r'[^\u4e00-\u9fffA-Za-z0-9\s\.,?!]', question) and len(question) > 20:
            non_chinese_ratio = len(re.findall(r'[^\u4e00-\u9fffA-Za-z0-9\s]', question)) / len(question)
            if non_chinese_ratio > 0.5:
                return False, "问题包含过多特殊字符，请重新输入"
        
        return True, "通过规则检查"
        """规则快速过滤"""
        question = question.strip()
        
        # 空检查
        if not question:
            return False, "问题不能为空"
        
        # 长度检查
        if len(question) < 2:
            return False, "问题太短，请提供更详细的描述"
        
        # 格式错误检查
        if question.count('?') > 3:
            return False, "问题格式异常"
        
        # 乱码检查
        if re.search(r'[^\u4e00-\u9fffA-Za-z0-9\s\.,?!]', question) and len(question) > 20:
            non_chinese_ratio = len(re.findall(r'[^\u4e00-\u9fffA-Za-z0-9\s]', question)) / len(question)
            if non_chinese_ratio > 0.5:
                return False, "问题包含过多特殊字符，请重新输入"
        
        return True, "通过规则检查"
    
    async def _model_based_check(self, question: str) -> Tuple[bool, str]:
        """TurnSense 模型完整性检查"""
        # TODO: 实际使用时调用 TurnSense 模型
        # 这里使用简单规则作为占位符
        return True, "通过语义检查"
    
    async def query_retrieval(self, query: str, timeout: int = 60) -> Dict:
        """调用检索层接口"""
        try:
            url = self.retrieval_url
            payload = {
                "query": query,
                "timeout": timeout,
                "return_raw": False
            }
            
            async with httpx.AsyncClient(timeout=timeout + 10) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return {
                            "success": True,
                            "answer": data.get("answer", ""),
                            "sources": data.get("sources", []),
                            "query": data.get("query", query),
                            "execution_time": data.get("execution_time", 0)
                        }
                    else:
                        return {
                            "success": False,
                            "error": data.get("error", "检索失败")
                        }
                else:
                    return {
                        "success": False,
                        "error": f"检索服务返回错误：{response.status_code}"
                    }
        except Exception as e:
            logger.error(f"检索调用失败：{e}")
            return {
                "success": False,
                "error": f"检索服务连接失败：{str(e)}"
            }
    
    async def record_to_context(self, session_id: str, user_message: str, assistant_message: str):
        """记录问答到上下文记忆服务"""
        try:
            # 记录用户提问
            url_user = f"{self.context_memory_url}/api/context/add-user-message"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(url_user, json={
                    "session_id": session_id,
                    "content": user_message
                })
            
            # 记录助手回答
            url_assistant = f"{self.context_memory_url}/api/context/add-assistant-message"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(url_assistant, json={
                    "session_id": session_id,
                    "content": assistant_message
                })
            
            logger.info(f"已记录问答到 session: {session_id}")
        except Exception as e:
            logger.error(f"记录到上下文记忆失败：{e}")
    
    async def process(self, question: str, session_id: str = None) -> Dict:
        """
        完整 NLU 处理流程
        
        流程：
        1. 指代判断 → 2. 上下文加载 → 3. 指代替换 → 4. 查询改写 → 
        5. 完整性检查 → 6. 检索 → 7. 记录上下文
        
        返回：
        {
            "success": bool,
            "answer": str,
            "sources": list,
            "error": str,
            "processing_steps": dict
        }
        """
        processing_steps = {}
        
        # 1. 指代判断
        has_pron = self.has_pronoun(question)
        processing_steps["has_pronoun"] = has_pron
        
        # 2. 如果有指代词，加载历史上下文
        if has_pron and session_id:
            history = await self.get_context_history(session_id, turns=2)
            processing_steps["history_loaded"] = len(history) > 0
            
            if history:
                # 3. 指代替换
                resolved_question, replaced = self.resolve_pronoun(question, history)
                processing_steps["pronoun_resolved"] = replaced
                processing_steps["original_question"] = question
                processing_steps["resolved_question"] = resolved_question
                question = resolved_question
            else:
                processing_steps["history_empty"] = True
        
        # 4. 查询改写
        rewritten_question = await self.rewrite_query(question)
        processing_steps["query_rewritten"] = rewritten_question
        
        # 5. 完整性检查
        is_complete, message = await self.check_completeness(rewritten_question)
        processing_steps["completeness_check"] = {
            "is_complete": is_complete,
            "message": message
        }
        
        if not is_complete:
            return {
                "success": False,
                "answer": None,
                "sources": [],
                "error": message,
                "processing_steps": processing_steps
            }
        
        # 6. 调用检索层
        retrieval_result = await self.query_retrieval(rewritten_question)
        processing_steps["retrieval"] = {
            "success": retrieval_result.get("success"),
            "execution_time": retrieval_result.get("execution_time")
        }
        
        if not retrieval_result.get("success"):
            return {
                "success": False,
                "answer": None,
                "sources": [],
                "error": retrieval_result.get("error", "检索失败"),
                "processing_steps": processing_steps
            }
        
        # 7. 记录到上下文记忆
        if session_id:
            answer_text = retrieval_result.get("answer", "")
            await self.record_to_context(session_id, rewritten_question, answer_text)
            processing_steps["context_recorded"] = True
        
        return {
            "success": True,
            "answer": retrieval_result.get("answer"),
            "sources": retrieval_result.get("sources", []),
            "error": None,
            "processing_steps": processing_steps
        }


# 单例模式
_pipeline_instance = None

def get_nlu_pipeline():
    """获取 NLU 流水线单例"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = NLUPipeline()
    return _pipeline_instance

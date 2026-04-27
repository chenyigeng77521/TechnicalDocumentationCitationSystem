# -*- coding: utf-8 -*-
"""
上下文记忆服务
负责管理 session 级别的对话历史（纯内存，不持久化）
"""

import uuid
from typing import Dict, List, Optional
from config import MAX_CONVERSATIONS


class MemoryService:
    """上下文记忆服务 - 纯内存存储"""
    
    def __init__(self):
        self.sessions: Dict[str, List[dict]] = {}
        print(f"✅ Context Memory 服务启动（纯内存模式，最多保存{MAX_CONVERSATIONS}组问答）")
    
    def create_session(self) -> str:
        """创建新 session，返回 session_id"""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        self.sessions[session_id] = []
        print(f"✅ 创建新 session: {session_id}")
        return session_id
    
    def add_user_message(self, session_id: str, content: str) -> bool:
        """添加用户提问（一问的开始）"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        # 添加用户消息
        self.sessions[session_id].append({
            "role": "user",
            "content": content
        })
        
        # 检查是否需要删除最旧的对话
        conversation_count = (len(self.sessions[session_id]) + 1) // 2
        if conversation_count > MAX_CONVERSATIONS:
            # 删除最旧的两条记录（一问一答）
            self.sessions[session_id] = self.sessions[session_id][2:]
            print(f"📝 Session {session_id} 超出限制，删除最旧对话")
        
        return True
    
    def add_assistant_message(self, session_id: str, content: str) -> bool:
        """添加助手回答（一问一答的结束）"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        # 添加助手消息
        self.sessions[session_id].append({
            "role": "assistant",
            "content": content
        })
        
        return True
    
    def get_history(self, session_id: str) -> Optional[List[dict]]:
        """获取 session 的对话历史"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return None
        
        return self.sessions[session_id]
    
    def clear_session(self, session_id: str) -> bool:
        """清空 session 的对话历史"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        self.sessions[session_id] = []
        print(f"✅ 清空 session: {session_id}")
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """删除整个 session"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        del self.sessions[session_id]
        print(f"✅ 删除 session: {session_id}")
        return True
    
    def get_all_sessions(self) -> Dict[str, int]:
        """获取所有 session 及其对话数量"""
        return {sid: len(messages) for sid, messages in self.sessions.items()}
    
    def get_latest_question(self, session_id: str) -> Optional[str]:
        """获取 session 中最新的用户提问（用于检索前的上下文）"""
        if session_id not in self.sessions:
            return None
        
        messages = self.sessions[session_id]
        # 从后往前找第一个 user 消息
        for msg in reversed(messages):
            if msg["role"] == "user":
                return msg["content"]
        
        return None


# 全局单例
memory_service = MemoryService()

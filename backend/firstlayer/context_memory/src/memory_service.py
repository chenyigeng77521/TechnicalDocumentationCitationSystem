# -*- coding: utf-8 -*-
"""
上下文记忆服务
负责管理 session 级别的对话历史（纯内存，不持久化）
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional
from config import MAX_CONVERSATIONS


class MemoryService:
    """上下文记忆服务 - 纯内存存储"""
    
    def __init__(self):
        # 数据结构：{session_id: {
        #   "created_at": "2026-01-15T10:30:00Z",
        #   "history": [
        #     {"records": 1, "timestamp": "...", "user": "...", "assistant": "..."},
        #     {"records": 2, "timestamp": "...", "user": "...", "assistant": "..."}
        #   ]
        # }}
        self.sessions: Dict[str, dict] = {}
        print(f"✅ Context Memory 服务启动（纯内存模式，最多保存{MAX_CONVERSATIONS}组问答）")
    
    def create_session(self) -> str:
        """创建新 session，返回 session_id"""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        self.sessions[session_id] = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "history": []
        }
        print(f"✅ 创建新 session: {session_id}")
        return session_id
    
    def add_user_message(self, session_id: str, content: str) -> bool:
        """添加用户提问（一问的开始）"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        # 检查当前是否有未完成的对话（只有 user 没有 assistant）
        history = self.sessions[session_id]["history"]
        if history and history[-1].get("assistant") is None:
            # 上一条记录还没有 assistant 回答，更新这条记录
            history[-1]["user"] = content
            history[-1]["timestamp"] = datetime.utcnow().isoformat() + "Z"
        else:
            # 创建新的对话记录
            records = len(history) + 1
            history.append({
                "records": records,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "user": content,
                "assistant": None
            })
        
        # 检查是否需要删除最旧的对话
        conversation_count = len(history)
        if conversation_count > MAX_CONVERSATIONS:
            # 删除最旧的记录
            self.sessions[session_id]["history"] = history[-MAX_CONVERSATIONS:]
            print(f"📝 Session {session_id} 超出限制，删除最旧对话")
        
        return True
    
    def add_assistant_message(self, session_id: str, content: str) -> bool:
        """添加助手回答（一问一答的结束）"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        history = self.sessions[session_id]["history"]
        if not history or history[-1].get("assistant") is not None:
            print(f"⚠️ 没有待回答的 user 消息")
            return False
        
        # 更新最后一条记录的 assistant 字段
        history[-1]["assistant"] = content
        # 更新 timestamp（回答时间）
        history[-1]["timestamp"] = datetime.utcnow().isoformat() + "Z"
        
        return True
    
    def get_history(self, session_id: str) -> Optional[dict]:
        """获取 session 的对话历史（返回完整结构）"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return None
        
        return self.sessions[session_id]
    
    def get_all_messages(self, session_id: str) -> Optional[List[dict]]:
        """获取 session 的所有消息列表
        
        Returns:
            消息列表，每条消息包含 records, timestamp, user, assistant
        """
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return None
        
        return self.sessions[session_id]["history"]
    
    def clear_session(self, session_id: str) -> bool:
        """清空 session 的对话历史"""
        if session_id not in self.sessions:
            print(f"❌ Session 不存在：{session_id}")
            return False
        
        self.sessions[session_id]["history"] = []
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
        return {sid: len(data["history"]) for sid, data in self.sessions.items()}
    
    def get_latest_question(self, session_id: str) -> Optional[str]:
        """获取 session 中最新的用户提问（用于检索前的上下文）"""
        if session_id not in self.sessions:
            return None
        
        history = self.sessions[session_id]["history"]
        # 从后往前找第一个有 user 消息的记录
        for record in reversed(history):
            if record.get("user"):
                return record["user"]
        
        return None
    
    def get_all_conversations(self) -> List[dict]:
        """获取所有 session 的所有问答记录
        
        Returns:
            所有问答记录列表，每条记录包含 session_id, created_at, records, timestamp, user, assistant
        """
        all_conversations = []
        
        for session_id, session_data in self.sessions.items():
            created_at = session_data["created_at"]
            for record in session_data["history"]:
                conversation_record = {
                    "session_id": session_id,
                    "created_at": created_at,
                    "records": record["records"],
                    "timestamp": record["timestamp"],
                    "user": record.get("user", ""),
                    "assistant": record.get("assistant", "")
                }
                all_conversations.append(conversation_record)
        
        # 按时间戳排序（从旧到新）
        all_conversations.sort(key=lambda x: x["timestamp"])
        
        return all_conversations
    
    def get_latest_conversations(self, session_id: str, count: int = 2) -> Optional[List[dict]]:
        """获取 session 中最近的 N 组问答（一问一答算一组）
        
        Args:
            session_id: session ID
            count: 获取多少组问答，默认 2 组
        
        Returns:
            最近的 N 组问答列表，每条记录包含 records, timestamp, user, assistant
        """
        if session_id not in self.sessions:
            return None
        
        history = self.sessions[session_id]["history"]
        
        # 如果记录不足 count 条，返回所有记录
        if len(history) <= count:
            return history
        
        # 从后往前取最近的 count 条记录
        start_index = max(0, len(history) - count)
        return history[start_index:]


# 全局单例
memory_service = MemoryService()

# -*- coding: utf-8 -*-
"""
上下文记忆服务客户端
调用 context_memory 服务 (端口 3006)
"""
import httpx
from typing import Optional, List, Dict


class ContextMemoryClient:
    """上下文记忆服务 HTTP 客户端"""

    def __init__(self, base_url: str = None):
        from config import Config
        self.base_url = base_url or Config.CONTEXT_MEMORY_URL
        self.timeout = 10.0

    async def get_latest_conversations(self, session_id: str, count: int = 2) -> Optional[List[Dict]]:
        """
        获取 session 中最近的 N 组问答
        
        Args:
            session_id: session ID
            count: 获取多少组问答，默认 2 组
            
        Returns:
            最近的 N 组问答列表，每组包含 user 和 assistant 消息
            如果 session 不存在或请求失败，返回 None
        """
        url = f"{self.base_url}/api/context/get-latest-conversations/{session_id}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params={"count": count})

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return data.get("conversations", [])
                    else:
                        print(f"⚠️ 获取上下文失败: {data.get('message', 'Unknown error')}")
                        return None
                else:
                    print(f"⚠️ 获取上下文失败，状态码: {response.status_code}")
                    return None

        except httpx.ConnectError:
            print(f"⚠️ 上下文记忆服务连接失败: {self.base_url}")
            return None
        except httpx.TimeoutException:
            print(f"⚠️ 获取上下文超时")
            return None
        except Exception as e:
            print(f"⚠️ 获取上下文异常: {str(e)}")
            return None

    async def get_history(self, session_id: str) -> Optional[List[Dict]]:
        """
        获取 session 的完整对话历史
        
        Args:
            session_id: session ID
            
        Returns:
            对话历史列表，如果失败返回 None
        """
        url = f"{self.base_url}/api/context/get-history/{session_id}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return data.get("history", [])
                    else:
                        return None
                else:
                    return None

        except Exception as e:
            print(f"⚠️ 获取历史异常: {str(e)}")
            return None

    def format_context(self, conversations: List[Dict]) -> str:
        """
        将对话列表格式化为上下文字符串
        
        Args:
            conversations: 对话列表
            
        Returns:
            格式化的上下文字符串
        """
        if not conversations:
            return ""

        context_lines = []
        for msg in conversations:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                context_lines.append(f"用户: {content}")
            elif role == "assistant":
                context_lines.append(f"助手: {content}")

        return "\n".join(context_lines)


# 全局单例
_context_client_instance = None


def get_context_client() -> ContextMemoryClient:
    """获取上下文记忆客户端单例"""
    global _context_client_instance
    if _context_client_instance is None:
        _context_client_instance = ContextMemoryClient()
    return _context_client_instance

# -*- coding: utf-8 -*-
"""
检索层客户端
调用检索层接口 http://172.25.178.29:18020/query
"""
import httpx
from typing import Optional, Dict, Any


class RetrievalClient:
    """检索层 HTTP 客户端"""

    def __init__(self, base_url: str = None):
        from config import Config
        self.base_url = base_url or Config.RETRIEVAL_URL
        self.timeout = 120.0  # 检索层设置 60s 超时

    async def query(self, query: str, timeout: int = 120, return_raw: bool = False) -> Dict[str, Any]:
        """
        调用检索层查询接口
        
        Args:
            query: 查询问题
            timeout: 超时时间（秒）
            return_raw: 是否返回原始输出
            
        Returns:
            检索结果字典
        """
        payload = {
            "query": query,
            "timeout": timeout,
            "return_raw": return_raw
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.base_url, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": data.get("success", False),
                        "query": data.get("query", query),
                        "answer": data.get("answer", ""),
                        "sources": data.get("sources", []),
                        "error": data.get("error"),
                        "execution_time": data.get("execution_time", 0),
                        "timestamp": data.get("timestamp", ""),
                        "metadata": data.get("metadata", {})
                    }
                else:
                    error_msg = f"检索层返回错误，状态码: {response.status_code}"
                    print(f"⚠️ {error_msg}")
                    return {
                        "success": False,
                        "query": query,
                        "answer": "",
                        "sources": [],
                        "error": error_msg,
                        "execution_time": 0,
                        "timestamp": "",
                        "metadata": {}
                    }

        except httpx.ConnectError:
            error_msg = f"检索层连接失败: {self.base_url}"
            print(f"⚠️ {error_msg}")
            return {
                "success": False,
                "query": query,
                "answer": "",
                "sources": [],
                "error": error_msg,
                "execution_time": 0,
                "timestamp": "",
                "metadata": {}
            }
        except httpx.TimeoutException:
            error_msg = "检索层请求超时"
            print(f"⚠️ {error_msg}")
            return {
                "success": False,
                "query": query,
                "answer": "",
                "sources": [],
                "error": error_msg,
                "execution_time": 0,
                "timestamp": "",
                "metadata": {}
            }
        except Exception as e:
            error_msg = f"检索层请求异常: {str(e)}"
            print(f"⚠️ {error_msg}")
            return {
                "success": False,
                "query": query,
                "answer": "",
                "sources": [],
                "error": error_msg,
                "execution_time": 0,
                "timestamp": "",
                "metadata": {}
            }


# 全局单例
_retrieval_client_instance = None


def get_retrieval_client() -> RetrievalClient:
    """获取检索层客户端单例"""
    global _retrieval_client_instance
    if _retrieval_client_instance is None:
        _retrieval_client_instance = RetrievalClient()
    return _retrieval_client_instance

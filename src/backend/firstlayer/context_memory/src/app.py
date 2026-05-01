# -*- coding: utf-8 -*-
"""
Context Memory 服务主入口
FastAPI 服务，提供上下文记忆管理 API
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict
import config
from memory_service import memory_service

app = FastAPI(
    title="Context Memory Service",
    description="上下文记忆服务 - 记录最近 30 次问答",
    version="1.0.0"
)


# 请求模型
class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class AddMessageRequest(BaseModel):
    session_id: str
    content: str


class SessionIdRequest(BaseModel):
    session_id: str


# 响应模型
class CreateSessionResponse(BaseModel):
    success: bool
    session_id: str
    message: str


class AddMessageResponse(BaseModel):
    success: bool
    message: str


class MessageRecord(BaseModel):
    records: int
    timestamp: str
    user: str
    assistant: Optional[str]


class SessionHistoryResponse(BaseModel):
    success: bool
    session_id: str
    created_at: Optional[str]
    history: Optional[List[MessageRecord]]
    total_records: int


class GetHistoryResponse(BaseModel):
    success: bool
    session_id: str
    history: Optional[List[dict]]
    conversation_count: int


class ClearSessionResponse(BaseModel):
    success: bool
    message: str


class GetAllSessionsResponse(BaseModel):
    success: bool
    sessions: Dict[str, int]


class GetAllMessagesResponse(BaseModel):
    success: bool
    session_id: str
    created_at: Optional[str]
    messages: Optional[List[MessageRecord]]
    total_count: int


class GetAllConversationsResponse(BaseModel):
    success: bool
    total_sessions: int
    total_conversations: int
    conversations: List[dict]


# API 路由
@app.get("/")
async def root():
    """服务健康检查"""
    return {
        "service": "Context Memory Service",
        "status": "running",
        "port": config.PORT
    }


@app.post("/api/context/create-session", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建新 session"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [create-session] 收到请求")
    
    try:
        session_id = memory_service.create_session()
        # 📝 调用接口后日志（成功）
        logger.info(f"✅ [create-session] 接口调用成功 - session_id: {session_id}")
        return CreateSessionResponse(
            success=True,
            session_id=session_id,
            message="Session 创建成功"
        )
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [create-session] 接口调用失败 - error: {str(e)}")
        return CreateSessionResponse(
            success=False,
            session_id="",
            message=f"创建失败：{str(e)}"
        )


@app.post("/api/context/add-user-message", response_model=AddMessageResponse)
async def add_user_message(request: AddMessageRequest):
    """添加用户提问（一问的开始）"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [add-user-message] 收到请求 - session_id: {request.session_id}, content: {request.content[:30]}...")
    
    try:
        success = memory_service.add_user_message(request.session_id, request.content)
        if success:
            # 📝 调用接口后日志（成功）
            logger.info(f"✅ [add-user-message] 接口调用成功 - session_id: {request.session_id}")
            return AddMessageResponse(success=True, message="用户消息已记录")
        else:
            logger.warning(f"⚠️ [add-user-message] Session 不存在 - session_id: {request.session_id}")
            return AddMessageResponse(success=False, message="Session 不存在")
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [add-user-message] 接口调用失败 - error: {str(e)}")
        return AddMessageResponse(success=False, message=f"添加失败：{str(e)}")


@app.post("/api/context/add-assistant-message", response_model=AddMessageResponse)
async def add_assistant_message(request: AddMessageRequest):
    """添加助手回答（一问一答的结束）"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [add-assistant-message] 收到请求 - session_id: {request.session_id}, content: {request.content[:30]}...")
    
    try:
        success = memory_service.add_assistant_message(request.session_id, request.content)
        if success:
            # 📝 调用接口后日志（成功）
            logger.info(f"✅ [add-assistant-message] 接口调用成功 - session_id: {request.session_id}")
            return AddMessageResponse(success=True, message="助手消息已记录")
        else:
            logger.warning(f"⚠️ [add-assistant-message] Session 不存在 - session_id: {request.session_id}")
            return AddMessageResponse(success=False, message="Session 不存在")
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [add-assistant-message] 接口调用失败 - error: {str(e)}")
        return AddMessageResponse(success=False, message=f"添加失败：{str(e)}")


@app.get("/api/context/get-history/{session_id}", response_model=SessionHistoryResponse)
async def get_history(session_id: str):
    """获取 session 的对话历史（完整结构）
    
    返回格式：
    {
        "session_id": "sess_12345",
        "created_at": "2026-01-15T10:30:00Z",
        "history": [
            {
                "records": 1,
                "timestamp": "2026-01-15T10:30:15Z",
                "user": "华为 Mate60 Pro 充电速度怎么样？",
                "assistant": "支持 88W 有线快充，30 分钟可充至 80%。"
            },
            {
                "records": 2,
                "timestamp": "2026-01-15T10:32:08Z",
                "user": "它的续航表现呢？",
                "assistant": "内置 5000mAh 电池，重度使用续航约 8 小时。"
            }
        ],
        "total_records": 2
    }
    """
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [get-history] 收到请求 - session_id: {session_id}")
    
    try:
        data = memory_service.get_history(session_id)
        if data is None:
            logger.warning(f"⚠️ [get-history] Session 不存在 - session_id: {session_id}")
            return SessionHistoryResponse(
                success=False,
                session_id=session_id,
                created_at=None,
                history=None,
                total_records=0
            )
        
        # 📝 调用接口后日志（成功）
        logger.info(f"✅ [get-history] 接口调用成功 - session_id: {session_id}, total_records: {len(data['history'])}")
        return SessionHistoryResponse(
            success=True,
            session_id=session_id,
            created_at=data["created_at"],
            history=data["history"],
            total_records=len(data["history"])
        )
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [get-history] 接口调用失败 - error: {str(e)}")
        return SessionHistoryResponse(
            success=False,
            session_id=session_id,
            created_at=None,
            history=None,
            total_records=0
        )


@app.get("/api/context/get-all-messages/{session_id}", response_model=GetAllMessagesResponse)
async def get_all_messages(session_id: str):
    """获取 session 的所有消息列表
    
    返回格式：
    {
        "success": true,
        "session_id": "sess_12345",
        "created_at": "2026-01-15T10:30:00Z",
        "messages": [
            {
                "records": 1,
                "timestamp": "2026-01-15T10:30:15Z",
                "user": "华为 Mate60 Pro 充电速度怎么样？",
                "assistant": "支持 88W 有线快充，30 分钟可充至 80%。"
            },
            {
                "records": 2,
                "timestamp": "2026-01-15T10:32:08Z",
                "user": "它的续航表现呢？",
                "assistant": "内置 5000mAh 电池，重度使用续航约 8 小时。"
            }
        ],
        "total_count": 2
    }
    """
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [get-all-messages] 收到请求 - session_id: {session_id}")
    
    try:
        data = memory_service.get_history(session_id)
        if data is None:
            logger.warning(f"⚠️ [get-all-messages] Session 不存在 - session_id: {session_id}")
            return GetAllMessagesResponse(
                success=False,
                session_id=session_id,
                created_at=None,
                messages=None,
                total_count=0
            )
        
        # 📝 调用接口后日志（成功）
        logger.info(f"✅ [get-all-messages] 接口调用成功 - session_id: {session_id}, total_count: {len(data['history'])}")
        return GetAllMessagesResponse(
            success=True,
            session_id=session_id,
            created_at=data["created_at"],
            messages=data["history"],
            total_count=len(data["history"])
        )
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [get-all-messages] 接口调用失败 - error: {str(e)}")
        return GetAllMessagesResponse(
            success=False,
            session_id=session_id,
            created_at=None,
            messages=None,
            total_count=0
        )


@app.post("/api/context/clear-session", response_model=ClearSessionResponse)
async def clear_session(request: SessionIdRequest):
    """清空 session 的对话历史"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [clear-session] 收到请求 - session_id: {request.session_id}")
    
    try:
        success = memory_service.clear_session(request.session_id)
        if success:
            # 📝 调用接口后日志（成功）
            logger.info(f"✅ [clear-session] 接口调用成功 - session_id: {request.session_id}")
            return ClearSessionResponse(success=True, message="Session 已清空")
        else:
            logger.warning(f"⚠️ [clear-session] Session 不存在 - session_id: {request.session_id}")
            return ClearSessionResponse(success=False, message="Session 不存在")
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [clear-session] 接口调用失败 - error: {str(e)}")
        return ClearSessionResponse(success=False, message=f"清空失败：{str(e)}")


@app.delete("/api/context/delete-session/{session_id}", response_model=ClearSessionResponse)
async def delete_session(session_id: str):
    """删除整个 session"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [delete-session] 收到请求 - session_id: {session_id}")
    
    try:
        success = memory_service.delete_session(session_id)
        if success:
            # 📝 调用接口后日志（成功）
            logger.info(f"✅ [delete-session] 接口调用成功 - session_id: {session_id}")
            return ClearSessionResponse(success=True, message="Session 已删除")
        else:
            logger.warning(f"⚠️ [delete-session] Session 不存在 - session_id: {session_id}")
            return ClearSessionResponse(success=False, message="Session 不存在")
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [delete-session] 接口调用失败 - error: {str(e)}")
        return ClearSessionResponse(success=False, message=f"删除失败：{str(e)}")


@app.get("/api/context/get-all-sessions", response_model=GetAllSessionsResponse)
async def get_all_sessions():
    """获取所有 session 及其对话数量"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [get-all-sessions] 收到请求")
    
    try:
        sessions = memory_service.get_all_sessions()
        # 📝 调用接口后日志（成功）
        logger.info(f"✅ [get-all-sessions] 接口调用成功 - total_sessions: {len(sessions)}")
        return GetAllSessionsResponse(success=True, sessions=sessions)
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [get-all-sessions] 接口调用失败 - error: {str(e)}")
        return GetAllSessionsResponse(success=False, sessions={})


@app.get("/api/context/get-latest-question/{session_id}")
async def get_latest_question(session_id: str):
    """获取 session 中最新的用户提问"""
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [get-latest-question] 收到请求 - session_id: {session_id}")
    
    try:
        question = memory_service.get_latest_question(session_id)
        if question:
            # 📝 调用接口后日志（成功）
            logger.info(f"✅ [get-latest-question] 接口调用成功 - session_id: {session_id}")
            return {"success": True, "question": question}
        else:
            logger.warning(f"⚠️ [get-latest-question] Session 不存在或无提问 - session_id: {session_id}")
            return {"success": False, "question": None, "message": "Session 不存在或无提问"}
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [get-latest-question] 接口调用失败 - error: {str(e)}")
        return {"success": False, "question": None, "message": str(e)}


@app.get("/api/context/get-latest-conversations/{session_id}")
async def get_latest_conversations(session_id: str, count: int = 2):
    """获取 session 中最近的 N 条消息记录
    
    Args:
        session_id: session ID
        count: 获取多少条记录，默认 2 条
    
    Returns:
        最近的 N 条消息记录列表
    """
    try:
        conversations = memory_service.get_latest_conversations(session_id, count)
        if conversations is None:
            return {"success": False, "conversations": [], "message": "Session 不存在"}
        
        return {
            "success": True,
            "conversations": conversations,
            "total_count": len(conversations),
            "requested_count": count
        }
    except Exception as e:
        return {"success": False, "conversations": [], "message": str(e)}


@app.get("/api/context/get-all-conversations", response_model=GetAllConversationsResponse)
async def get_all_conversations():
    """获取所有 session 的所有问答记录
    
    返回格式：
    {
        "success": true,
        "total_sessions": 5,
        "total_conversations": 23,
        "conversations": [
            {
                "session_id": "session_abc123",
                "created_at": "2026-04-29T10:30:00Z",
                "records": 1,
                "timestamp": "2026-04-29T10:30:15Z",
                "user": "iPhone 15 多少钱？",
                "assistant": "iPhone 15 售价 5999 元起。"
            },
            {
                "session_id": "session_def456",
                "created_at": "2026-04-29T10:35:00Z",
                "records": 1,
                "timestamp": "2026-04-29T10:35:20Z",
                "user": "它支持快充吗？",
                "assistant": "支持 20W 快充。"
            }
        ]
    }
    
    说明：
    - 按时间戳排序（从旧到新）
    - 包含所有 session 的所有问答记录
    - 适用于数据分析、审计、统计等场景
    """
    # 📝 调用接口前日志
    import logging
    logger = logging.getLogger("context_memory")
    logger.info(f"📥 [get-all-conversations] 收到请求")
    
    try:
        conversations = memory_service.get_all_conversations()
        total_sessions = len(memory_service.sessions)
        
        # 📝 调用接口后日志（成功）
        logger.info(f"✅ [get-all-conversations] 接口调用成功 - total_sessions: {total_sessions}, total_conversations: {len(conversations)}")
        
        return GetAllConversationsResponse(
            success=True,
            total_sessions=total_sessions,
            total_conversations=len(conversations),
            conversations=conversations
        )
    except Exception as e:
        # 📝 调用接口后日志（错误）
        logger.error(f"❌ [get-all-conversations] 接口调用失败 - error: {str(e)}")
        return GetAllConversationsResponse(
            success=False,
            total_sessions=0,
            total_conversations=0,
            conversations=[]
        )




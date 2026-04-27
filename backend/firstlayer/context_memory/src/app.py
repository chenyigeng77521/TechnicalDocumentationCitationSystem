# -*- coding: utf-8 -*-
"""
Context Memory 服务主入口
FastAPI 服务，提供上下文记忆管理 API
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
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
    pass


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
    try:
        session_id = memory_service.create_session()
        return CreateSessionResponse(
            success=True,
            session_id=session_id,
            message="Session 创建成功"
        )
    except Exception as e:
        return CreateSessionResponse(
            success=False,
            session_id="",
            message=f"创建失败：{str(e)}"
        )


@app.post("/api/context/add-user-message", response_model=AddMessageResponse)
async def add_user_message(request: AddMessageRequest):
    """添加用户提问（一问的开始）"""
    try:
        success = memory_service.add_user_message(request.session_id, request.content)
        if success:
            return AddMessageResponse(success=True, message="用户消息已记录")
        else:
            return AddMessageResponse(success=False, message="Session 不存在")
    except Exception as e:
        return AddMessageResponse(success=False, message=f"添加失败：{str(e)}")


@app.post("/api/context/add-assistant-message", response_model=AddMessageResponse)
async def add_assistant_message(request: AddMessageRequest):
    """添加助手回答（一问一答的结束）"""
    try:
        success = memory_service.add_assistant_message(request.session_id, request.content)
        if success:
            return AddMessageResponse(success=True, message="助手消息已记录")
        else:
            return AddMessageResponse(success=False, message="Session 不存在")
    except Exception as e:
        return AddMessageResponse(success=False, message=f"添加失败：{str(e)}")


@app.get("/api/context/get-history/{session_id}", response_model=GetHistoryResponse)
async def get_history(session_id: str):
    """获取 session 的对话历史"""
    try:
        history = memory_service.get_history(session_id)
        if history is None:
            return GetHistoryResponse(
                success=False,
                session_id=session_id,
                history=None,
                conversation_count=0
            )
        
        # 一问一答算一组
        conversation_count = len(history) // 2
        
        return GetHistoryResponse(
            success=True,
            session_id=session_id,
            history=history,
            conversation_count=conversation_count
        )
    except Exception as e:
        return GetHistoryResponse(
            success=False,
            session_id=session_id,
            history=None,
            conversation_count=0
        )


@app.post("/api/context/clear-session", response_model=ClearSessionResponse)
async def clear_session(request: SessionIdRequest):
    """清空 session 的对话历史"""
    try:
        success = memory_service.clear_session(request.session_id)
        if success:
            return ClearSessionResponse(success=True, message="Session 已清空")
        else:
            return ClearSessionResponse(success=False, message="Session 不存在")
    except Exception as e:
        return ClearSessionResponse(success=False, message=f"清空失败：{str(e)}")


@app.delete("/api/context/delete-session/{session_id}", response_model=ClearSessionResponse)
async def delete_session(session_id: str):
    """删除整个 session"""
    try:
        success = memory_service.delete_session(session_id)
        if success:
            return ClearSessionResponse(success=True, message="Session 已删除")
        else:
            return ClearSessionResponse(success=False, message="Session 不存在")
    except Exception as e:
        return ClearSessionResponse(success=False, message=f"删除失败：{str(e)}")


@app.get("/api/context/get-all-sessions", response_model=GetAllSessionsResponse)
async def get_all_sessions():
    """获取所有 session 及其对话数量"""
    try:
        sessions = memory_service.get_all_sessions()
        return GetAllSessionsResponse(success=True, sessions=sessions)
    except Exception as e:
        return GetAllSessionsResponse(success=False, sessions={})


@app.get("/api/context/get-latest-question/{session_id}")
async def get_latest_question(session_id: str):
    """获取 session 中最新的用户提问"""
    try:
        question = memory_service.get_latest_question(session_id)
        if question:
            return {"success": True, "question": question}
        else:
            return {"success": False, "question": None, "message": "Session 不存在或无提问"}
    except Exception as e:
        return {"success": False, "question": None, "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    print(f"🚀 Context Memory Service 启动中...")
    print(f"📍 端口：{config.PORT}")
    print(f"📍 地址：http://0.0.0.0:{config.PORT}")
    print(f"📚 API 文档：http://localhost:{config.PORT}/docs")
    uvicorn.run(app, host=config.HOST, port=config.PORT)

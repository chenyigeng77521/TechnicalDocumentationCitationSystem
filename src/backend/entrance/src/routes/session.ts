/**
 * Session 管理路由
 * 由 entrance (3002) 统一生成 session，调用 context memory (3006)
 */

import { Router, Request, Response } from 'express';
import fetch from 'node-fetch';
import { config } from '../config.js';

const router = Router();

/**
 * POST /api/session/create
 * 创建新 session
 * entrance 调用 context memory 的 /api/context/create-session
 */
router.post('/create', async (req: Request, res: Response) => {
  try {
    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        message: 'Context Memory 服务未启用',
        error: 'ENABLE_CONTEXT_MEMORY not set'
      });
    }

    // 调用 context memory 的 create-session 接口
    const contextMemoryUrl = `${config.contextMemory.url}/api/context/create-session`;
    console.log(`✅ 调用 Context Memory 创建 session: ${contextMemoryUrl}`);

    const response = await fetch(contextMemoryUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
      timeout: config.contextMemory.timeout,
    } as any);

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`✅ Context Memory 返回错误:`, response.status, errorText);
      return res.status(response.status).json({
        success: false,
        message: '创建 session 失败',
        error: errorText,
        statusCode: response.status,
      });
    }

    const data = await response.json();
    console.log(`✅ Session 创建成功:`, data.session_id);

    res.json({
      success: true,
      session_id: data.session_id,
      created_at: new Date().toISOString(),
    });

  } catch (error: any) {
    console.error('✅ 创建 session 失败:', error.message);
    res.status(500).json({
      success: false,
      message: '创建 session 失败',
      error: error.message,
    });
  }
});

/**
 * GET /api/session/validate/:session_id
 * 验证 session 是否有效
 */
router.get('/validate/:session_id', async (req: Request, res: Response) => {
  try {
    const { session_id } = req.params;

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        message: 'Context Memory 服务未启用',
      });
    }

    // 调用 context memory 获取 session 信息
    const contextMemoryUrl = `${config.contextMemory.url}/api/context/get-history/${session_id}`;
    console.log(`✅ 验证 session: ${session_id}`);

    const response = await fetch(contextMemoryUrl, {
      method: 'GET',
      timeout: config.contextMemory.timeout,
    } as any);

    if (!response.ok) {
      return res.json({
        success: false,
        valid: false,
        message: 'Session 不存在或已过期',
        session_id,
      });
    }

    const data = await response.json();
    res.json({
      success: true,
      valid: true,
      session_id,
      conversation_count: data.conversations?.length || 0,
    });

  } catch (error: any) {
    console.error('✅ 验证 session 失败:', error.message);
    res.status(500).json({
      success: false,
      message: '验证 session 失败',
      error: error.message,
    });
  }
});

/**
 * GET /api/session/info/:session_id
 * 获取 session 详细信息
 */
router.get('/info/:session_id', async (req: Request, res: Response) => {
  try {
    const { session_id } = req.params;

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        message: 'Context Memory 服务未启用',
      });
    }

    // 调用 context memory 获取 session 信息
    const contextMemoryUrl = `${config.contextMemory.url}/api/context/get-latest-conversations/${session_id}`;
    console.log(`✅ 获取 session 信息: ${session_id}`);

    const response = await fetch(contextMemoryUrl, {
      method: 'GET',
      timeout: config.contextMemory.timeout,
    } as any);

    if (!response.ok) {
      return res.status(response.status).json({
        success: false,
        message: '获取 session 信息失败',
        session_id,
      });
    }

    const data = await response.json();
    res.json({
      success: true,
      session_id,
      conversations: data.conversations || [],
      total_conversations: data.conversations?.length || 0,
    });

  } catch (error: any) {
    console.error('✅ 获取 session 信息失败:', error.message);
    res.status(500).json({
      success: false,
      message: '获取 session 信息失败',
      error: error.message,
    });
  }
});

export default router;

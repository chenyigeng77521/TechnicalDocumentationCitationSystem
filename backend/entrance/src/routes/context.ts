/**
 * Context Memory 代理路由
 * 由 entrance 服务 (3002) 代理调用 context memory 服务 (3006)
 */

import { Router, Request, Response } from 'express';
import fetch from 'node-fetch';
import { config } from '../config.js';

const router = Router();

/**
 * GET /api/context/create-session
 * 创建新 session（entrance 调用 context memory 服务）
 */
router.get('/create-session', async (req: Request, res: Response) => {
  try {
    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        error: 'Context Memory 服务未启用'
      });
    }

    // 调用 context memory 服务创建 session
    const createResp = await fetch(
      `${config.contextMemory.url}/api/context/create-session`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      }
    );

    if (!createResp.ok) {
      throw new Error(`Context Memory 服务返回错误：${createResp.status}`);
    }

    const data: any = await createResp.json();
    res.json(data);
  } catch (error: any) {
    console.error('❌ 创建 session 失败:', error.message);
    res.status(500).json({
      success: false,
      error: `创建 session 失败：${error.message}`
    });
  }
});

/**
 * GET /api/context/get-history/:session_id
 * 获取完整对话历史（所有问答对）
 */
router.get('/get-all-messages/:session_id', async (req: Request, res: Response) => {
  try {
    const { session_id } = req.params;

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        error: 'Context Memory 服务未启用'
      });
    }

    const resp = await fetch(
      `${config.contextMemory.url}/api/context/get-all-messages/${session_id}`,
      { method: 'GET' }
    );

    if (!resp.ok) {
      throw new Error(`Context Memory 服务返回错误：${resp.status}`);
    }

    const data: any = await resp.json();
    res.json(data);
  } catch (error: any) {
    console.error('❌ 获取完整历史失败:', error.message);
    res.status(500).json({
      success: false,
      error: `获取完整历史失败：${error.message}`
    });
  }
});

/**
 * GET /api/context/get-latest-conversations/:session_id
 * 获取最近 N 组问答
 */
router.get('/get-latest-conversations/:session_id', async (req: Request, res: Response) => {
  try {
    const { session_id } = req.params;
    const limit = parseInt(req.query.limit as string) || 10;

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        error: 'Context Memory 服务未启用'
      });
    }

    const resp = await fetch(
      `${config.contextMemory.url}/api/context/get-latest-conversations/${session_id}?limit=${limit}`,
      { method: 'GET' }
    );

    if (!resp.ok) {
      throw new Error(`Context Memory 服务返回错误：${resp.status}`);
    }

    const data: any = await resp.json();
    res.json(data);
  } catch (error: any) {
    console.error('❌ 获取历史对话失败:', error.message);
    res.status(500).json({
      success: false,
      error: `获取历史对话失败：${error.message}`
    });
  }
});

/**
 * POST /api/context/add-user-message
 * 添加用户消息
 */
router.post('/add-user-message', async (req: Request, res: Response) => {
  try {
    const { session_id, content } = req.body;

    if (!session_id || !content) {
      return res.status(400).json({
        success: false,
        error: '缺少必要参数：session_id, content'
      });
    }

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        error: 'Context Memory 服务未启用'
      });
    }

    const resp = await fetch(
      `${config.contextMemory.url}/api/context/add-user-message`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id, content })
      }
    );

    if (!resp.ok) {
      throw new Error(`Context Memory 服务返回错误：${resp.status}`);
    }

    const data: any = await resp.json();
    res.json(data);
  } catch (error: any) {
    console.error('❌ 添加用户消息失败:', error.message);
    res.status(500).json({
      success: false,
      error: `添加用户消息失败：${error.message}`
    });
  }
});

/**
 * POST /api/context/add-assistant-message
 * 添加助手消息
 */
router.post('/add-assistant-message', async (req: Request, res: Response) => {
  try {
    const { session_id, content } = req.body;

    if (!session_id || !content) {
      return res.status(400).json({
        success: false,
        error: '缺少必要参数：session_id, content'
      });
    }

    if (!config.contextMemory.enabled) {
      return res.status(503).json({
        success: false,
        error: 'Context Memory 服务未启用'
      });
    }

    const resp = await fetch(
      `${config.contextMemory.url}/api/context/add-assistant-message`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id, content })
      }
    );

    if (!resp.ok) {
      throw new Error(`Context Memory 服务返回错误：${resp.status}`);
    }

    const data: any = await resp.json();
    res.json(data);
  } catch (error: any) {
    console.error('❌ 添加助手消息失败:', error.message);
    res.status(500).json({
      success: false,
      error: `添加助手消息失败：${error.message}`
    });
  }
});

export default router;

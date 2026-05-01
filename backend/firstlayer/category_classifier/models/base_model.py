# -*- coding: utf-8 -*-
"""
模型基类 - 提供懒加载机制
"""
import torch
from abc import ABC, abstractmethod
from typing import Any


class BaseModelClient(ABC):
    """模型客户端基类 - 懒加载模式"""

    def __init__(self, model_name: str, device: str = None):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None
        self._tokenizer = None
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def ensure_loaded(self):
        """确保模型已加载（懒加载）"""
        if not self._is_loaded:
            self.load_model()

    @abstractmethod
    def load_model(self):
        """加载模型 - 子类必须实现"""
        pass

    def to_device(self, tensor: Any) -> Any:
        """将 tensor 移到指定设备"""
        if torch.is_tensor(tensor):
            return tensor.to(self.device)
        return tensor

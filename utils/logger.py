"""
日志模块
统一管理全项目日志输出，同时写入文件和控制台
"""
import logging
from pathlib import Path
from config.settings import LOG_DIR


def setup_logger(name: str = "quant", level: int = logging.INFO) -> logging.Logger:
    """
    创建/获取一个配置好的 Logger

    Args:
        name: logger名称
        level: 日志级别

    Returns:
        配置好的Logger实例
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # 避免重复添加handler
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 文件输出
    file_handler = logging.FileHandler(
        LOG_DIR / "quant.log", encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

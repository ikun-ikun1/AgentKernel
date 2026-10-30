"""兼容 shim：MySQL ngram 适配器已移到 adapters/knowledge/mysql_ngram.py（A4）。"""

from __future__ import annotations

from agentkernel.adapters.knowledge.mysql_ngram import MySQLKnowledgeError, MySQLKnowledgeStore

__all__ = ["MySQLKnowledgeError", "MySQLKnowledgeStore"]

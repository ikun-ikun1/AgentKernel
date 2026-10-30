"""兼容 shim：MySQL ngram 适配器已移到 adapters/knowledge/mysql_ngram.py（A4）。"""

from __future__ import annotations

from agentkernel._compat import warn_deprecated

warn_deprecated("agentkernel.rag.mysql_store", "agentkernel.adapters.knowledge.mysql_ngram")

from agentkernel.adapters.knowledge.mysql_ngram import MySQLKnowledgeError, MySQLKnowledgeStore

__all__ = ["MySQLKnowledgeError", "MySQLKnowledgeStore"]

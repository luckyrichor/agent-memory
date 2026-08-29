from enum import Enum, IntEnum


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryStatus(str, Enum):
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ScopeKind(str, Enum):
    TENANT = "tenant"
    WORKSPACE = "workspace"
    USER_GLOBAL = "user_global"
    USER_WORKSPACE = "user_workspace"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class AuthorityLevel(IntEnum):
    AGENT_INFERENCE = 0
    SINGLE_EVENT = 1
    MULTIPLE_EVENTS = 2
    TOOL_VERIFIED = 3
    USER_CONFIRMED = 4
    ENTERPRISE_POLICY = 5
